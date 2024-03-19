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

def w(msg):
    print(f"{msg}", file=sys.stderr, flush=True)

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
        self.message_id:Optional[str] = None

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

    def __init__(self, mail_body:str):
        super().__init__()

        S  = RakutenPayPlainText
        R  = self._get_record
        NY = _normalize_yen
        ND = _normalize_datetime

        lines = mail_body.split("\n")
        self.datetime   = ND(R(lines, S.RE_DATETIME))
        self.receipt_no = R(lines, S.RE_RECEIPT_NO)
        self.store_name = R(lines, S.RE_STORE_NAME)
        self.store_tel  = R(lines, S.RE_STORE_TEL)

        legacy_mail = self._is_legacy_mail(lines)
        if legacy_mail:
            self.use_point = 0
            self.use_cash  = NY(R(lines, S.RE_PAY_CASH_L))
            self.total     = NY(R(lines, S.RE_TOTAL))
        else:
            point          = R(lines, S.RE_PAY_POINT)
            self.use_point = int(point) if point is not None else None
            self.use_cash  = NY(R(lines, S.RE_PAY_CASH))
            self.total     = NY(R(lines, S.RE_TOTAL))

    def _get_record(self, lines, regex: re.Pattern):
        for line in lines:
            m = regex.search(line)
            if m:
                return m.group(1).strip()
        w(f'PlainText:element not found:{regex}')
        return None

    def _is_legacy_mail(self, lines:List[str]):
        search = RakutenPayPlainText.RE_PAY_CASH_L.search
        return any(search(line) for line in lines)

#=== html mail ===
class RakutenPayHTMLMailUtil:
    def get_next_sibling_text(self, bs:bs4.BeautifulSoup, target_regex:str):
        node = bs.find(string=re.compile(target_regex))
        text = (''.join(node.parent.parent.next_sibling.next_sibling.strings)).strip()
        return text
HTMLUtil = RakutenPayHTMLMailUtil()

class RakutenPayMailHtml2018(RakutenPayMail):
    #"：" が無いとHTMLのコメントにマッチして死ぬ…
    RE_KEYWORD = re.compile('ご利用ポイント(/キャッシュ)?上限：')

    def __init__(self, mail_body:str):
        super().__init__()
        NP = _normalize_point
        ND = _normalize_datetime
        GN = HTMLUtil.get_next_sibling_text

        bs = bs4.BeautifulSoup(mail_body, features='html.parser')
        self.datetime   = ND(GN(bs, 'お申込日：'))
        self.receipt_no = GN(bs, 'お申込番号：').strip()
        self.store_name = GN(bs, 'ご利用サイト：')
        self.store_tel  = ''
        self.use_point  = NP(GN(bs, 'ご利用ポイント(/キャッシュ)?上限：'))
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
        self.use_cash   = NY(self._get_right_text(bs, 'ポイント(/キャッシュ)?利用：'))
        self.total      = NY(self._get_right_text(bs, '小計：'))

    def _get_right_text(self, bs, key: str):
        target_node = bs.find(string=re.compile(key))
        text = (''.join(target_node.parent.next_sibling.next_sibling.strings)).strip()
        return text

class UnexcpectedRakutenPayMailException(Exception):
    def __init__(self):
        self.stack_trace_list:List[Exception] = None
        self.mail_body:str = None
        self.from_:str     = None
        self.subject:str   = None
        self.msgid:str     = None
        self.email:Message = None

# === parser ===
def _parse_mailbody_html(mail_body:str):
    # if 'お客様のお申込情報を受けた時点で送信される自動配信メール' in mail_body:
    #    e(f'{filePath} / ignore...')
    #    wrap = ''
    if RakutenPayMailHtml2018.RE_KEYWORD.search(mail_body):
        return RakutenPayMailHtml2018(mail_body)
    if RE_PRE_ELEMENT.search(mail_body):
        return RakutenPayMailLegacy(mail_body)
    else:
        return RakutenPayMailCurrent(mail_body)

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

def _get_rakuten_pay_mail_first(msg:Message):
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
            return parse_mailbody(mail_body)
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

    if ('order@checkout.rakuten.co.jp' in from_) and ('楽天ペイ お申込完了' not in subject):
        return True
    if ('no-reply@pay.rakuten.co.jp' in from_) and ('ご利用内容確認メール' in subject):
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

        pay_mail = _get_rakuten_pay_mail_first(mail)
        pay_mail.message_id = msgid
        return pay_mail
    except UnexcpectedRakutenPayMailException as ex:
        ex.from_   = from_
        ex.subject = subject
        ex.msgid   = msgid
        raise

def parse_str(mail_body:str, from_:str, subject:str):
    if not is_rakuten_pay_mail(from_, subject):
        return None
    return parse_mailbody(mail_body)

def parse_mailbody(mail_body:str) -> RakutenPayMail:
    """
    Raises:
        throw various exceptions....
        Caller must catch exceptions.
    """
    if RE_IS_HTML.search(mail_body):
        return _parse_mailbody_html(mail_body)
    else:
        return RakutenPayPlainText(mail_body)

def _main():
    mail_body = ''.join(sys.stdin)
    result = parse_mailbody(mail_body)
    print(result)

if __name__ == '__main__':
    _main()
