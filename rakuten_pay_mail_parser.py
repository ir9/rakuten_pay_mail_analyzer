from typing import *
import re
import sys
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
    print(f"{msg}", sys.stderr)

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

RE_REMOVE_WEEK = re.compile(r'[（\()][月火水木金土日][）\)]')
def _normalize_datetime(s: str):
    s = RE_REMOVE_WEEK.sub('', s)
    return dateutil.parser.parse(s)

class RakutenPayMail:
    datetime:Optional[dt.datetime] = None
    receipt_no:Optional[str] = None
    store_name:Optional[str] = None
    store_tel:Optional[str]  = None
    use_point:Optional[int]  = None
    '利用したポイント'
    use_cash:Optional[int]   = None
    '利用したcache'
    total:Optional[int]      = None
    '支払総額'

    def __init__(self):
        pass

    def __str__(self):
        return f"DateTime: {self.datetime} / Total: {self.total} / Point:{self.use_point} / ReceiptNo: {self.receipt_no} / Store: {self.store_name} / Tel: {self.store_tel}"

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

    def __init__(self, mail_body: str):
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
            self.use_point  = 0
            self.use_cash  = NY(R(lines, S.RE_PAY_CASH_L))
            self.total      = NY(R(lines, S.RE_TOTAL))
        else:
            self.use_point  = int(R(lines, S.RE_PAY_POINT))
            self.use_cash  = NY(R(lines, S.RE_PAY_CASH))
            self.total      = NY(R(lines, S.RE_TOTAL))

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

class RakutenPayMailLegacy(RakutenPayMail):
    RE_BODY_EXTRACTOR = re.compile(r"<pre>(.+?)</pre>", re.S)

    def __init__(self, mailBody: str):
        super().__init__()
        NY = _normalize_yen
        ND = _normalize_datetime
        self.lines = self._extractBody(mailBody)

        self.datetime   = ND(self._getValue('注文日'))
        self.receipt_no = self._getValue('注文番号')
        self.store_name = self._getValue('□利用店舗')
        self.store_tel  = ''
        self.use_cash   = NY(self._getValue('ポイント利用').replace('ポイント）', ''))
        self.total      = NY(self._getValue('合計金額').replace('（円）', ''))

    def _extractBody(self, mailBody: str):
        S = RakutenPayMailLegacy
        m = S.RE_BODY_EXTRACTOR.search(mailBody)
        body = m.group(1)
        return body.split('\n')

    def _getValue(self, key: str):
        line = [line for line in self.lines if key in line][0]
        # print(line)
        kv   = line.split('：')
        value = kv[1].strip()
        return value

class RakutenPayMailCurrent(RakutenPayMail):
    def __init__(self, mailBody: str):
        super().__init__()
        NY = _normalize_yen
        ND = _normalize_datetime
        self.bs = bs4.BeautifulSoup(mailBody, features='lxml')

        self.datetime   = ND(self._getNextSiblingText('ご注文日：'))
        self.receipt_no = self._getNextSiblingText('ご注文番号：')
        self.store_name = self._getNextSiblingText('ご利用サイト：')
        self.store_tel  = ''
        self.use_cash   = NY(self._getRightText('ポイント(/キャッシュ)?利用：'))
        self.total      = NY(self._getRightText('小計：'))

    def _getNextSiblingText(self, prevKey: str):
        targetNode = self.bs.find(string=re.compile(prevKey))
        text = (''.join(targetNode.parent.parent.next_sibling.next_sibling.strings)).strip()
        return text

    def _getRightText(self, key: str):
        # targetNode = self.bs.find(string=re.compile('お支払い金額：'))
        targetNode = self.bs.find(string=re.compile(key))
        text = (''.join(targetNode.parent.next_sibling.next_sibling.strings)).strip()
        return text

class UnexcpectedRakutenPayMailException(Exception):
    def __init__(self):
        self.mail_body:str = None
        self.from_:str     = None
        self.subject:str   = None
        self.email:Message = None

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
        # print(f"{body}:{encode}", file=sys.stderr)
        if isinstance(body, str):
            return body
        else:
            return util.decode(body, encode)

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
    return util.decode(body, charset)

def _content_type_is_text_plain(part:Message):
    return part.get_content_type() == 'text/plain'

def _get_rakuten_pay_mail_first(msg:Message):
    msgid = _decode_header(msg, 'Message-ID')
    for i, part in enumerate(filter(_content_type_is_text_plain, msg.walk())):
        mail_body = 'decode failed...'
        try:
            mail_body = _get_mail_body(part)
            return parse_mailbody(mail_body)
        except Exception as ex:
            _dump_mail(mail_body, msgid, filename, i)
            w(f'unexcepted rakuten pay mail format(1): {filename} / {msgid}, {ex}, {traceback.format_exc()}')
            continue

    w(f'unexcepted rakuten pay mail format(2): {filename} / {msgid}, {traceback.format_exc()}')
    return None

#=== api ===
def is_rakuten_pay_mail(from_:str, subject:str):
    from_   = from_   or ''
    subject = subject or ''

    if 'order@checkout.rakuten.co.jp' in from_:
        return True
    elif ('no-reply@pay.rakuten.co.jp' in from_) and ('ご利用内容確認メール' in subject):
        return True
    return False

def parse_email(mail:Message):
    msgid   = _decode_header(mail, 'Message-ID')
    subject = _decode_header(mail, 'subject')
    from_   = _decode_header(mail, 'from')
    # print(f"{from_} / {subject}")
    if not is_rakuten_pay_mail(from_, subject):
        return None
    if not mail.is_multipart():
        return None # 楽天Payのmailは必ず multipart

    pay_mail = _get_rakuten_pay_mail_first(mail)
    return pay_mail

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
        # if 'お客様のお申込情報を受けた時点で送信される自動配信メール' in mail_body:
        #    e(f'{filePath} / ignore...')
        #    wrap = ''
        if RE_PRE_ELEMENT.search(mail_body):
            return RakutenPayMailLegacy(mail_body)
        else:
            return RakutenPayMailCurrent(mail_body)
    else:
        return RakutenPayPlainText(mail_body)

def _main():
    mail_body = ''.join(sys.stdin)
    result = parse(mail_body)
    print(result)

if __name__ == '__main__':
    _main()
