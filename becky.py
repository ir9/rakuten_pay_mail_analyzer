from typing import *
import sys
import os.path
import glob
import argparse
import email
import email.header
from email.message import Message

import rakuten_pay_mail_parser
import util

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



def get_rakuten_pay_mails(mail_box_path:str):
    for bmf_file in glob.glob('**/*.bmf', root_dir=mail_box_path, recursive=True):
        print('.', file=sys.stderr, end='', flush=True)
        bmf_path = os.path.join(mail_box_path, bmf_file)
        msgid = None
        try:
            for mail in split_becky_mailfile(bmf_path):
                msg     = email.message_from_bytes(mail)
                msgid   = decode_header(msg, 'Message-ID') or ''
                subject = decode_header(msg, 'subject')    or ''
                from_   = decode_header(msg, 'from')       or ''
                # print(f"{from_} / {subject}")
                if not rakuten_pay_mail_parser.is_rakuten_pay_mail(from_, subject):
                    continue
                if not msg.is_multipart():
                    continue # 楽天Payのmailは必ず multipart

                mail = get_rakuten_pay_mail_first(msg, bmf_file)
                if mail:
                    msgid = decode_header(msg, 'Message-ID')
                    yield (mail, msgid)
        except Exception as ex:
            print(f"{bmf_file}:{msgid}:{ex}")
            raise


def get_cli_option():
    p = argparse.ArgumentParser()
    p.add_argument('mail_box_path', help='specify the directory to *.bkl files.')
    return p.parse_args()


def main():
    opt = get_cli_option()
    mail_box_path = opt.mail_box_path
    mails = list(get_rakuten_pay_mails(mail_box_path))
    for mail, msgid in mails:
        print(','.join(map(str, [mail.datetime, mail.total, mail.use_point, mail.use_cash, mail.store_name, msgid])))

if __name__ == '__main__':
    main()

