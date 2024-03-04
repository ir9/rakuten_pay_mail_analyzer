from typing import *
import sys
import os.path
import glob
import argparse
import traceback
import quopri
import base64
import email
import email.header
from email.message import Message

import rakuten_pay_mail_parser

def _dump_mail(msg:str, filename:str):
    with open(filename, "a", encoding='utf-8') as h:
        print(msg, file=h, end='')

def w(msg:str):
    print(f"{msg}", file=sys.stderr)

END_OF_EMAIL = b'\r\n.\r\n'
END_OF_EMAIL_LENGTH = len(END_OF_EMAIL)

def find_eoe_index(mail:bytes, start_index:int):
    for i in range(start_index, len(mail)):
        if mail[i:i+END_OF_EMAIL_LENGTH] == END_OF_EMAIL:
            return i
    return None

def split_becky_mailfile(bkl_filepath:str):
    with open(bkl_filepath, "rb") as h:
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


TRANS_DECODE_MAP:dict[str, Callable[[Any], bytes]] = {
    'base64':           base64.b64decode,
    'quoted-printable': quopri.decodestring,
}

def get_mail_body(msg:Message):
    charset        = msg.get_content_charset()
    trans_encoding = decode_header(msg, 'Content-Transfer-Encoding')
    print(f"{charset} / {trans_encoding}")
    raw_body = msg.get_payload()

    body = TRANS_DECODE_MAP[trans_encoding](raw_body)
    return body.decode(charset)

def content_type_is_text_plain(part:Message):
    return part.get_content_type() == 'text/plain'

def get_rakuten_pay_mail_first(msg:Message, filename:str):
    msgid = decode_header(msg, 'Message-ID')
    for part in filter(content_type_is_text_plain, msg.walk()):
        try:
            mail_body = get_mail_body(part)
            # _dump_mail(mail_body, "dump.txt")
            return rakuten_pay_mail_parser.parse(mail_body)
        except Exception as ex:
            w(f'unexcepted rakuten pay mail format(1): {filename} / {msgid}, {ex}, {traceback.format_exc()}')
            continue

    w(f'unexcepted rakuten pay mail format(2): {filename} / {msgid}, {traceback.format_exc()}')
    return None

def get_rakuten_pay_mails(mail_box_path:str):
    search_path = os.path.join(mail_box_path, "*.bkl")
    for bkl_file in glob.glob(search_path):
        for mail in split_becky_mailfile(bkl_file):
            msg = email.message_from_bytes(mail)
            subject = decode_header(msg, 'subject')
            from_   = decode_header(msg, 'from')
            # print(f"{from_} / {subject}")
            if not rakuten_pay_mail_parser.is_rakuten_pay_mail(from_, subject):
                continue
            if not msg.is_multipart():
                continue # 楽天Payのmailは必ず multipart

            mail = get_rakuten_pay_mail_first(msg, bkl_file)
            if mail:
                yield mail


def get_cli_option():
    p = argparse.ArgumentParser()
    p.add_argument('mail_box_path', help='specify the directory to *.bkl files.')
    return p.parse_args()


def main():
    opt = get_cli_option()
    mail_box_path = opt.mail_box_path
    mails = list(get_rakuten_pay_mails(mail_box_path))
    for mail in mails:
        print(','.join(map(str, [mail.datetime, mail.total, mail.use_point, mail.store_name])))

if __name__ == '__main__':
    main()

