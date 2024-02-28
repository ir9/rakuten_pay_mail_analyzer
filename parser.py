from typing import *
import re
import sys
import quopri
import base64
import email
import email.header
from email.message import Message

import bs4
import colorama
import dateutil.parser

def w(msg):
    print(f"{colorama.Fore.YELLOW}{msg}{colorama.Fore.RESET}")

def e(msg):
    print(f"{colorama.Fore.RED}{msg}{colorama.Fore.RESET}", file=sys.stderr)


# ============================
# rakuten mail spec
# ============================
RE_IS_HTML     = re.compile('<html.*?>', re.I)
RE_PRE_ELEMENT = re.compile('<pre.*?>', re.I)

def _mkRe(key: str):
    return re.compile(r'\s+%s\s+(.+)' % key)

def _normalizeYen(s: str):
    REMOVE_CHARS = ',円 '
    v = functools.reduce(lambda prev, curr: prev.replace(curr, ''), REMOVE_CHARS, s)
    return int(v)

RE_REMOVE_WEEK = re.compile(r'[（\()][月火水木金土日][）\)]')
def _normalizeDateTime(s: str):
    s = RE_REMOVE_WEEK.sub('', s)
    return dateutil.parser.parse(s)

class RakutenPayPlainText:
    RE_DATETIME   = _mkRe("ご利用日時")
    RE_RECEIPT_NO = _mkRe("伝票番号")
    RE_STORE_NAME = _mkRe("ご利用店舗")
    RE_STORE_TEL  = _mkRe("電話番号")
    RE_TOTAL      = _mkRe("決済総額")
    RE_PAY_POINT  = _mkRe("ポイント／キャッシュ利用")
    RE_PAY_CASH   = _mkRe("お支払金額")

    def __init__(self, filePath: str, mailBody: str):
        S = RakutenPayPlainText
        R = self._getRecord
        NY = _normalizeYen
        ND = _normalizeDateTime

        self.filePath = filePath

        lines = mailBody.split("\n")
        self.datetime   = ND(R(lines, S.RE_DATETIME))
        self.receipt_no = R(lines, S.RE_RECEIPT_NO)
        self.store_name = R(lines, S.RE_STORE_NAME)
        self.store_tel  = R(lines, S.RE_STORE_TEL)
        self.use_point  = NY(R(lines, S.RE_PAY_POINT))
        self.total      = NY(R(lines, S.RE_TOTAL))

    def _getRecord(self, lines, regex: re.Pattern):
        for line in lines:
            m = regex.search(line)
            if m:
                return m.group(1).strip()
        w(f'PlainText:{self.filePath}:element not found:{regex}')
        return None

    def __str__(self):
        return f"DateTime: {self.datetime} / Total: {self.total} / Point:{self.use_point} / ReceiptNo: {self.receipt_no} / Store: {self.store_name} / Tel: {self.store_tel}"


class RakutenPayHtmlMailBase:
    def __init__(self, filePath: str):
        self.filePath = filePath
        self.datetime   = None
        self.receipt_no = None
        self.store_name = None
        self.store_tel  = None
        self.use_point  = None
        self.total      = None

    def __str__(self):
        return f"DateTime: {self.datetime} / Total: {self.total} / Point:{self.use_point} / ReceiptNo: {self.receipt_no} / Store: {self.store_name} / Tel: {self.store_tel}"

class RakutenPayHtmlMailLegacy(RakutenPayHtmlMailBase):
    RE_BODY_EXTRACTOR = re.compile(r"<pre>(.+?)</pre>", re.S)

    def __init__(self, filePath: str, mailBody: str):
        super().__init__(filePath)
        NY = _normalizeYen
        ND = _normalizeDateTime
        self.lines = self._extractBody(mailBody)

        self.datetime   = ND(self._getValue('注文日'))
        self.receipt_no = self._getValue('注文番号')
        self.store_name = self._getValue('□利用店舗')
        self.store_tel  = ''
        self.use_point  = NY(self._getValue('ポイント利用').replace('ポイント）', ''))
        self.total      = NY(self._getValue('合計金額').replace('（円）', ''))

    def _extractBody(self, mailBody: str):
        S = RakutenPayHtmlMailLegacy
        m = S.RE_BODY_EXTRACTOR.search(mailBody)
        body = m.group(1)
        return body.split('\n')

    def _getValue(self, key: str):
        line = [line for line in self.lines if key in line][0]
        # print(line)
        kv   = line.split('：')
        value = kv[1].strip()
        return value

class RakutenPayHtmlMailCurrent(RakutenPayHtmlMailBase):
    def __init__(self, filePath: str, mailBody: str):
        super().__init__(filePath)
        NY = _normalizeYen
        ND = _normalizeDateTime
        self.bs = bs4.BeautifulSoup(mailBody, features='lxml')

        self.datetime   = ND(self._getNextSiblingText('ご注文日：'))
        self.receipt_no = self._getNextSiblingText('ご注文番号：')
        self.store_name = self._getNextSiblingText('ご利用サイト：')
        self.store_tel  = ''
        self.use_point  = NY(self._getRightText('ポイント(/キャッシュ)?利用：'))
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

#===========================-
END_OF_EMAIL = b'\r\n.\r\n'
END_OF_EMAIL_LENGTH = len(END_OF_EMAIL)

def find_eoe_index(mail:bytes, start_index:int):
    for i in range(start_index, len(mail)):
        if mail[i:i+5] == END_OF_EMAIL:
            return i
    return None


def split_becky_mailfile(filename_list:list[str]):
    for filename in filename_list:
        with open(filename, "rb") as h:
            file = h.read()

        start_index = 0
        eoe_index   = find_eoe_index(file, start_index)
        while eoe_index is not None:
            yield file[start_index: eoe_index+END_OF_EMAIL_LENGTH]
            start_index = eoe_index + END_OF_EMAIL_LENGTH
            eoe_index   = find_eoe_index(file, start_index)
        rem = file[start_index:]
        if len(rem) > 0:
            yield file[start_index:]

def decode_header(msg:Message, key:str):
    def decode(seg:Tuple):
        body, encode = seg
        # print(f"{body}:{encode}")
        if isinstance(body, str):
            return body
        else:
            return body.decode(encode or 'cp932')

    header = msg[key]
    if header is None:
        return None
    header = email.header.decode_header(header)
    return ''.join(map(decode, header))


TRANS_DECODE_MAP = {
    'base64':           base64.b64decode,
    'quoted-printable': quopri.decodestring,
}

def get_mail_body(msg:Message):
    charset        = msg.get_content_charset()
    trans_encoding = decode_header(msg, 'Content-Transfer-Encoding')
    print(f"{charset} / {trans_encoding}")
    raw_body = msg.get_payload()

    body:bytes = TRANS_DECODE_MAP[trans_encoding](raw_body)
    return body.decode(charset)

def is_rakuten_pay_mail(from_:str, subject:str):
    return (
        ('no-reply@pay.rakuten.co.jp' in from_) and ('ご利用内容確認メール' in subject)
    ) or (
        'order@checkout.rakuten.co.jp' in from_
    )

def content_type_is_text_plain(part:Message):
    return part.get_content_type() == 'text/plain'

def main():
    filelist = [
        '20240222.bkl',
        '20231007.bkl',
        '20231126.bkl',
    ]

    for mail in split_becky_mailfile(filelist):
        msg = email.message_from_bytes(mail)
        subject = decode_header(msg, 'subject')
        from_   = decode_header(msg, 'from')
        if not is_rakuten_pay_mail(from_, subject):
            continue

        date = decode_header(msg, 'Date')
        if msg.is_multipart():
            print(f"{from_} / {subject}")
            for part in filter(content_type_is_text_plain, msg.walk()):
                mail_body = get_mail_body(part)
                print(mail_body[:256])
                if RE_IS_HTML.search(mail_body):
                    try:
                        # if 'お客様のお申込情報を受けた時点で送信される自動配信メール' in mail_body:
                        #    e(f'{filePath} / ignore...')
                        #    wrap = ''
                        if RE_PRE_ELEMENT.search(mail_body):
                            wrap = RakutenPayHtmlMailLegacy(filePath, mail_body)
                        else:
                            wrap = RakutenPayHtmlMailCurrent(filePath, mail_body)
                    except Exception as ex:
                        e(f'{filePath} / ignore... / {ex}')
                        return
                else:
                    wrap = RakutenPayPlainText(filePath, mail_body)
        else:
            content_type   = msg.get_content_type()
            char_set       = msg.get_charset()
            trans_encoding = decode_header(msg, 'Content-Transfer-Encoding')
            print(f"=== {from_}:{subject}:{date}:{content_type}:{char_set}:{trans_encoding}")
            body = msg.get_payload()
            print(body)
    # print(f"found mails:{len(mail_list)}")
colorama.init()
main()

