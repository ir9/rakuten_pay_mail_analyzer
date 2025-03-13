from typing import *
import re
import sys
import io
import csv
import functools
import traceback
import quopri
import base64
import datetime as dt
import email
import email.header
from   email.message import Message

import bs4
import dateutil.parser
import util

class Mail(NamedTuple):
    body: str
    from_: str
    subject: str

def w(msg):
    print(f"{msg}", file=sys.stderr, flush=True)

V = TypeVar('V')
D = TypeVar('D')
def nullcoal(v:Optional[V], d:Optional[D]):
    return d if v is None else v

# ============================
# rakuten mail spec
# ============================
RE_IS_HTML     = re.compile('<html.*?>', re.I)
RE_PRE_ELEMENT = re.compile('<pre.*?>', re.I)

def _mk_re(key: str):
    return re.compile(rf'\s+{key}\s+(.+)')

def _normalize_yen(s: str):
    REMOVE_CHARS = ',円 '
    v = functools.reduce(lambda prev, curr: prev.replace(curr, ''), REMOVE_CHARS, s)
    return int(v)

def _normalize_point(s:str):
    return int(s.replace('ポイント', ''))

RE_REMOVE_WEEK = re.compile(r'[（\()][月火水木金土日][）\)]')
def _normalize_datetime(s: str):
    s = RE_REMOVE_WEEK.sub('', s)
    return dateutil.parser.parse(s)

_CSV_VALUE_HEADER = [
    'DateTime',
    'ReceiptNo',
    'Store',
    'Tel',
    'UsePoint',
    'UseCache',
    'Total',
    'Message-Id',
]
class RakutenPayMail:
    CSV_VALUE_HEADER = _CSV_VALUE_HEADER

    def __init__(self):
        self.datetime:Optional[dt.datetime] = None
        self.receipt_no:Optional[str] = None
        self.store_name:Optional[str] = None
        self.store_tel:Optional[str]  = None
        self.use_point:Optional[int]  = None
        self.use_cash:Optional[int]   = None
        self.total:Optional[int]      = None
        "ポイント/cash を引く前の支払い送金額"
        self.message_id:Optional[str] = None
        self.has_error = False

    def csv_rawvalues(self):
        vals = [
            str(self.datetime),
            str(self.receipt_no),
            str(self.store_name),
            str(self.store_tel),
            self.use_point,
            self.use_cash,
            self.total,
            self.message_id,
        ]
        def normalize(v):
            return '' if v is None else v

        return list(map(normalize, vals))

    def csv(self):
        out = io.StringIO()
        w   = csv.writer(out)
        w.writerow(self.csv_rawvalues())
        return out.getvalue()

    def __str__(self):
        vals = [
            ('DateTime',   self.datetime),
            ('ReceiptNo',  self.receipt_no),
            ('Store',      self.store_name),
            ('Tel',        self.store_tel),
            ('UsePoint',   self.use_point),
            ('UseCache',   self.use_cash),
            ('Total',      self.total),
            ('Message-Id', self.message_id),
        ]
        return ' / '.join(f'{key}: {val}' for key, val in vals)

class RakutenPayPlainText(RakutenPayMail):
    RE_DATETIME   = _mk_re("ご利用日時")
    RE_RECEIPT_NO = _mk_re("伝票番号")
    RE_STORE_NAME = _mk_re("ご利用店舗")
    RE_STORE_TEL  = _mk_re("電話番号")
    RE_TOTAL      = _mk_re("決済総額")

    # Legacy
    RE_PAY_CASH_L = _mk_re("ポイント／キャッシュ利用")

    # current
    RE_PAY_POINT  = _mk_re("ポイント")
    RE_PAY_CASH   = _mk_re("楽天キャッシュ")

    # suicaチャージ
    RE_SUICA_RECEIPT_NO = _mk_re("Suicaポケット発行依頼ID（伝票番号）")
    RE_SUICA_AMOUNT     = _mk_re('金額')

    # 国税
    RE_PAY_GOV_NAME = _mk_re("お支払先")
    RE_PAY_GOV_YEAR = _mk_re("課税年度")

    def __init__(self, mail_body:str):
        super().__init__()

        S  = RakutenPayPlainText
        NY = _normalize_yen
        ND = _normalize_datetime

        lines  = mail_body.split("\n")
        values = self._parse_values(lines)
        def V(pattern: re.Pattern): # bind 'values'
            return self._get_value(values, pattern)
        def VN(pattern: re.Pattern):
            return values[pattern]

        legacy_mail  = values[S.RE_PAY_CASH_L]   is not None
        kokuzei_mail = values[S.RE_PAY_GOV_YEAR] is not None
        suica_charge_mail = values[S.RE_SUICA_RECEIPT_NO] is not None

        self.datetime   = ND(V(S.RE_DATETIME))
        self.store_tel  = nullcoal(VN(S.RE_STORE_TEL), '')

        point = VN(S.RE_PAY_POINT)
        point = int(point) if point is not None else None

        if kokuzei_mail:
            gov_name = V(S.RE_PAY_GOV_NAME)
            gov_year = nullcoal(VN(S.RE_PAY_GOV_YEAR), '')

            self.use_point  = point
            self.receipt_no = V(S.RE_RECEIPT_NO)
            self.store_name = ' '.join([gov_name, gov_year]).strip()
            self.use_cash   = NY(V(S.RE_PAY_CASH))
            self.total      = NY(V(S.RE_TOTAL))
        elif suica_charge_mail:
            self.use_point  = ''
            self.store_name = "Suicaチャージ"
            self.receipt_no = V(S.RE_SUICA_RECEIPT_NO)
            self.use_cash   = ''
            self.total      = NY(V(S.RE_SUICA_AMOUNT))
        elif legacy_mail:
            self.use_point  = 0
            self.receipt_no = V(S.RE_RECEIPT_NO)
            self.store_name = V(S.RE_STORE_NAME)
            self.use_cash   = NY(V(S.RE_PAY_CASH_L))
            self.total      = NY(V(S.RE_TOTAL))
        else:
            self.use_point  = point
            self.receipt_no = V(S.RE_RECEIPT_NO)
            self.store_name = V(S.RE_STORE_NAME)
            self.use_cash   = NY(V(S.RE_PAY_CASH))
            self.total      = NY(V(S.RE_TOTAL))
    
    def _parse_values(self, lines) -> dict[re.Pattern, Optional[str]]:
        S = RakutenPayPlainText
        keys = [
            S.RE_DATETIME,
            S.RE_RECEIPT_NO,
            S.RE_STORE_NAME,
            S.RE_STORE_TEL,
            S.RE_TOTAL,
            S.RE_PAY_CASH_L,
            S.RE_PAY_POINT,
            S.RE_PAY_CASH,
            S.RE_SUICA_RECEIPT_NO,
            S.RE_SUICA_AMOUNT,            
            S.RE_PAY_GOV_NAME,
            S.RE_PAY_GOV_YEAR,            
        ]
        def _get_record(regex: re.Pattern) -> Optional[str]:
            for line in lines:
                m = regex.search(line)
                if m:
                    return m.group(1).strip()
            return None

        return { key : _get_record(key) for key in keys }

    def _get_value(self, dic: Dict[re.Pattern, Optional[str]], pattern: re.Pattern):
        value = dic[pattern]
        if value is None:
            w(f'PlainText:element not found:{pattern}')
            self.has_error = True
        return value

    def _is_target_mail(self, re_keyword: re.Pattern , lines:List[str]):
        search = re_keyword.search
        return any(search(line) for line in lines)

#=== html mail ===
class RakutenPayHTMLMailUtil:
    def get_next_sibling_text(self, bs:bs4.BeautifulSoup, prev_key:str):
        node = bs.find(string=re.compile(prev_key))
        text = (''.join(node.parent.parent.next_sibling.next_sibling.strings)).strip()
        return text
HTMLUtil = RakutenPayHTMLMailUtil()

class RakutenPayMailHtml2018(RakutenPayMail):
    """
    for
    - html00.html
    - html01.html ?
    """

    #"：" が無いとHTMLのコメントにマッチして死ぬ…
    KEYWORD = 'ご利用ポイント上限：'

    def __init__(self, mail_body:str):
        super().__init__()
        ND = _normalize_datetime
        GN = HTMLUtil.get_next_sibling_text

        bs = bs4.BeautifulSoup(mail_body, features='lxml')
        self.datetime   = ND(GN(bs, 'お申込日：'))
        self.receipt_no = GN(bs, 'お申込番号：').strip()
        self.store_name = GN(bs, 'ご利用サイト：')
        self.store_tel  = ''
        self.use_point  = GN(bs, 'ご利用ポイント上限：')
        self.use_cash   = None
        self.total      = None

    def _get_value(self, bs:bs4.BeautifulSoup, find_text:str):
        node = bs.find(string=re.compile(find_text))
        return ''.join(node.parent.parent.next_sibling.next_sibling.strings)

class RakutenPayMailLegacy(RakutenPayMail):
    RE_BODY_EXTRACTOR = re.compile(r"<pre>(.+?)</pre>", re.S)

    def __init__(self, mail_body:str):
        super().__init__()
        NY = _normalize_yen
        ND = _normalize_datetime
        self.lines = self._extract_body(mail_body)

        self.datetime   = ND(self._get_value('注文日'))
        self.receipt_no = self._get_value('注文番号')
        self.store_name = self._get_value('□利用店舗')
        self.store_tel  = ''
        self.use_cash   = NY(self._get_value('ポイント利用').replace('ポイント）', ''))
        self.total      = NY(self._get_value('合計金額').replace('（円）', ''))

    def _extract_body(self, mailBody: str):
        S = RakutenPayMailLegacy
        m = S.RE_BODY_EXTRACTOR.search(mailBody)
        body = m.group(1)
        return body.split('\n')

    def _get_value(self, key: str):
        line = [line for line in self.lines if key in line][0]
        # print(line)
        kv   = line.split('：')
        value = kv[1].strip()
        return value

class RakutenPayMailCurrent(RakutenPayMail):
    """
    for
    - html_current.html
    - html_current02.html
    """
    def __init__(self, mail_body: str):
        super().__init__()
        NY = _normalize_yen
        ND = _normalize_datetime
        GN = HTMLUtil.get_next_sibling_text
        bs = bs4.BeautifulSoup(mail_body, features='html.parser')

        self.datetime   = ND(GN(bs, 'ご注文日：'))
        self.receipt_no = GN(bs, 'ご注文番号：')
        self.store_name = GN(bs, 'ご利用サイト：')
        self.store_tel  = ''
        self.use_cash   = -NY(self._getRightText(bs, 'ポイント(/キャッシュ)?利用：'))
        self.total      = NY(self._getRightText(bs, '(小計|ご注文金額)：'))

    def _getRightText(self, bs, key: str):
        targetNode = bs.find(string=re.compile(key))
        text = (''.join(targetNode.parent.next_sibling.next_sibling.strings)).strip()
        return text

class RakutenPayMailOrderConfirm(RakutenPayMail):
    """
    for
    - order.html
    """
    def __init__(self, mail_body: str):
        super().__init__()
        NY = _normalize_yen
        ND = _normalize_datetime
        GN = HTMLUtil.get_next_sibling_text
        bs = bs4.BeautifulSoup(mail_body, features='html.parser')

        point = GN(bs, 'ご利用ポイント/キャッシュ上限：')
        point = point.replace("ポイント", '')

        self.datetime   = ND(GN(bs, 'お申込日：'))
        self.receipt_no = GN(bs, 'お申込番号：')
        self.store_name = GN(bs, 'お申込名：')
        self.store_tel  = ''
        self.use_cash   = int(point)
        self.total      = self.use_cash 

class UnexcpectedRakutenPayMailException(Exception):
    def __init__(self):
        self.stack_trace_list:List[Exception] = None
        self.mail_body:str = None
        self.from_:str     = None
        self.subject:str   = None
        self.msgid:str     = None
        self.email:Message = None

# === parser ===
def _parse_mailbody_html(mail:Mail):
    # if 'お客様のお申込情報を受けた時点で送信される自動配信メール' in mail_body:
    #    e(f'{filePath} / ignore...')
    #    wrap = ''
    subject = mail.subject
    from_   = mail.from_
    def is_order_confirm_mail():
        return 'order@checkout.rakuten.co.jp' in from_ and '楽天ペイ お申込完了' in subject

    if RakutenPayMailHtml2018.KEYWORD in mail.body:
        return RakutenPayMailHtml2018(mail.body)
    elif is_order_confirm_mail():
        return RakutenPayMailOrderConfirm(mail.body)
    elif RE_PRE_ELEMENT.search(mail.body):
        return RakutenPayMailLegacy(mail.body)
    else:
        return RakutenPayMailCurrent(mail.body)

#=== internal ===
def _dump_mail(mail_body:str, msgid:str, filename:str, i:int):
    # remove invalid chars in windows path
    for c in '\/:*?"<>|':
        msgid = msgid.replace(c, '')

    dump = f'{msgid}_{i}.txt'
    with open(dump, 'w', encoding='utf-8') as h:
        print(filename, file=h)
        print(msgid, file=h)
        print(file=h)
        print(mail_body, file=h, end='')

def _decode_header(msg:Message, key:str):
    def decode(seg:Tuple):
        body, encode = seg
        # print(f"{body}:{encode}:{mail_charset}:{mail_content_type}", file=sys.stderr)
        if isinstance(body, str):
            return body

        if encode in (None, 'unknown-8bit'):
            encode = msg.get_content_charset() # use the mail charset
        try:
            return util.decode(body, encode or 'cp932')
        except UnicodeDecodeError:
            msgid = msg['message-id']
            w(f'Header decode error...:{msgid}:{key}')
            return util.decode(body, encode or 'cp932', True)

    header = msg[key]
    if header is None:
        return None
    header = email.header.decode_header(header)
    return ''.join(map(decode, header))

TRANS_DECODE_MAP:dict[str, Callable[[Any], bytes]] = {
    'base64':           base64.b64decode,
    'quoted-printable': quopri.decodestring,
    '7bit':             quopri.decodestring,
}
def _get_mail_body(msg:Message):
    charset        = msg.get_content_charset()
    trans_encoding = _decode_header(msg, 'Content-Transfer-Encoding')
    # print(f"{charset} / {trans_encoding}")
    raw_body = msg.get_payload()

    body = TRANS_DECODE_MAP[trans_encoding](raw_body)
    try:
        return util.decode(body, charset)
    except UnicodeDecodeError:
        msgid = msg['mesasge-id']
        w(f'mailbody decode error...:{msgid}:{charset}:{trans_encoding}')
        return util.decode(body, charset, True)

def _content_type_is_text_plain(part:Message):
    return part.get_content_type() == 'text/plain'

def _get_rakuten_pay_mail_first(msg:Message, from_:str, subject:str):
    """
    Raises:
        UnexcpectedRakutenPayMailException
    """
    stack_trace_list = []
    msgid = _decode_header(msg, 'Message-ID')
    for part in filter(_content_type_is_text_plain, msg.walk()):
        mail_body = 'decode failed...'
        try:
            mail_body = _get_mail_body(part)
            return parse_mailbody(Mail(mail_body, from_, subject))
        except Exception as ex:
            w(f'unexcepted rakuten pay mail format(1): {msgid}, {ex}, {traceback.format_exc()}')
            stack_trace_list.append(traceback.format_exc())
            continue

    w(f'unexcepted rakuten pay mail format(2): {msgid}')
    ex = UnexcpectedRakutenPayMailException()
    ex.stack_trace_list = stack_trace_list
    ex.msgid = msgid
    ex.email = msg
    raise ex

#=== api ===
def is_rakuten_pay_mail(from_:str, subject:str):
    from_   = from_   or ''
    subject = subject or ''

    if ('order@checkout.rakuten.co.jp' in from_):
        return True
    if ('no-reply@pay.rakuten.co.jp' in from_):
        return True
    return False

def parse_email(mail:Message):
    """
    Raises:
        UnexcpectedRakutenPayMailException
    """

    subject = _decode_header(mail, 'subject')
    from_   = _decode_header(mail, 'from')
    msgid   = _decode_header(mail, 'Message-Id')
    # print(f"{from_} / {subject}")
    if not is_rakuten_pay_mail(from_, subject):
        return None

    try:
        if not mail.is_multipart():
            ex = UnexcpectedRakutenPayMailException()
            raise ex

        pay_mail = _get_rakuten_pay_mail_first(mail, from_, subject)
        pay_mail.message_id = msgid
        return pay_mail
    except UnexcpectedRakutenPayMailException as ex:
        ex.from_   = from_
        ex.subject = subject
        ex.msgid   = msgid
        raise

def parse_str(mail:Mail):
    if not is_rakuten_pay_mail(mail.from_, mail.subject):
        return None
    return parse_mailbody(mail)

def parse_mailbody(mail:Mail) -> RakutenPayMail:
    """
    Raises:
        throw various exceptions....
        Caller must catch exceptions.
    """
    if RE_IS_HTML.search(mail.body):
        return _parse_mailbody_html(mail)
    else:
        return RakutenPayPlainText(mail.body)

def _main():
    mail_body = ''.join(sys.stdin)
    result = parse_mailbody(mail_body)
    print(result)

if __name__ == '__main__':
    _main()
