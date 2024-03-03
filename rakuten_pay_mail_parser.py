from typing import *
import re
import sys
import functools

import bs4
import dateutil.parser

def w(msg):
    print(f"{msg}", sys.stderr)

# ============================
# rakuten mail spec
# ============================
RE_IS_HTML     = re.compile('<html.*?>', re.I)
RE_PRE_ELEMENT = re.compile('<pre.*?>', re.I)

def _mk_re(key: str):
    return re.compile(r'\s+%s\s+(.+)' % key)

def _normalize_yen(s: str):
    REMOVE_CHARS = ',円 '
    v = functools.reduce(lambda prev, curr: prev.replace(curr, ''), REMOVE_CHARS, s)
    return int(v)

RE_REMOVE_WEEK = re.compile(r'[（\()][月火水木金土日][）\)]')
def _normalize_datetime(s: str):
    s = RE_REMOVE_WEEK.sub('', s)
    return dateutil.parser.parse(s)

class RakutenPayHtmlMail:
    def __init__(self):
        self.datetime   = None
        self.receipt_no = None
        self.store_name = None
        self.store_tel  = None
        self.use_point  = None
        self.total      = None

    def __str__(self):
        return f"DateTime: {self.datetime} / Total: {self.total} / Point:{self.use_point} / ReceiptNo: {self.receipt_no} / Store: {self.store_name} / Tel: {self.store_tel}"

class RakutenPayPlainText(RakutenPayHtmlMail):
    RE_DATETIME   = _mk_re("ご利用日時")
    RE_RECEIPT_NO = _mk_re("伝票番号")
    RE_STORE_NAME = _mk_re("ご利用店舗")
    RE_STORE_TEL  = _mk_re("電話番号")
    RE_TOTAL      = _mk_re("決済総額")
    RE_PAY_POINT  = _mk_re("ポイント／キャッシュ利用")
    RE_PAY_CASH   = _mk_re("お支払金額")

    def __init__(self, mail_body: str):
        super().__init__()

        S = RakutenPayPlainText
        R = self._getRecord
        NY = _normalize_yen
        ND = _normalize_datetime

        lines = mail_body.split("\n")
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
        w(f'PlainText:element not found:{regex}')
        return None

class RakutenPayHtmlMailLegacy(RakutenPayHtmlMail):
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

class RakutenPayHtmlMailCurrent(RakutenPayHtmlMail):
    def __init__(self, mailBody: str):
        super().__init__()
        NY = _normalize_yen
        ND = _normalize_datetime
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

#=== api ===

def is_rakuten_pay_mail(from_:str, subject:str):
    if 'order@checkout.rakuten.co.jp' in from_:
        return True
    elif ('no-reply@pay.rakuten.co.jp' in from_) and ('ご利用内容確認メール' in subject):
        return True
    return False

def parse(mail_body:str) -> RakutenPayHtmlMail:
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
            return RakutenPayHtmlMailLegacy(mail_body)
        else:
            return RakutenPayHtmlMailCurrent(mail_body)
    else:
        return RakutenPayPlainText(mail_body)

def _main():
    mail_body = ''.join(sys.stdin)
    result = parse(mail_body)
    print(result)

if __name__ == '__main__':
    _main()
