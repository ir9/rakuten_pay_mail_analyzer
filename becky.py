from typing import *
import sys
import traceback
import os.path
import glob
import argparse
import email

import rakuten_pay_mail_parser as r_pay

def _dump_mail(msg:str, filename:str):
    with open(filename, "a", encoding='utf-8') as h:
        print(msg, file=h, end='')

def w(msg:str):
    print(f"{msg}", file=sys.stderr)

END_OF_EMAIL = b'\r\n.\r\n'
END_OF_EMAIL_LENGTH = len(END_OF_EMAIL)

def _find_eoe_index(mail:bytes, start_index:int):
    for i in range(start_index, len(mail)):
        if mail[i:i+END_OF_EMAIL_LENGTH] == END_OF_EMAIL:
            return i
    return None

def _split_becky_mailfile(bkl_filepath:str):
    with open(bkl_filepath, "rb") as h:
        file = h.read()

    start_index = 0
    eoe_index   = _find_eoe_index(file, start_index)
    while eoe_index is not None:
        yield file[start_index: eoe_index+END_OF_EMAIL_LENGTH]
        start_index = eoe_index + END_OF_EMAIL_LENGTH
        eoe_index   = _find_eoe_index(file, start_index)
    rem = file[start_index:]
    if len(rem) > 0:
        yield file[start_index:]

def parse_mail(bmf_path:str):
    msgid = None
    mail  = None
    try:
        for mail_raw in _split_becky_mailfile(bmf_path):
            mail  = email.message_from_bytes(mail_raw)
            msgid = r_pay._decode_header(mail, 'Message-ID')

            pay_mail = r_pay.parse_email(mail)
            if pay_mail:
                yield (pay_mail, msgid)
    except r_pay.UnexcpectedRakutenPayMailException:
        basename = os.path.basename(bmf_path)
        body = str(mail) + '\n\n' + traceback.format_exc()
        _dump_mail(body, f"{basename}_{msgid}.txt")
        w(f'Unexpected rakute pay mail format:{basename}:{msgid}:{traceback.format_exc()}')
        raise
    except Exception as ex:
        print(f"{bmf_path}:{msgid}:{ex}")
        raise

def get_rakuten_pay_mails(mail_box_path:str):
    for bmf_file in glob.glob('**/*.bmf', root_dir=mail_box_path, recursive=True):
        # print('.', file=sys.stderr, end='', flush=True)
        bmf_path = os.path.join(mail_box_path, bmf_file)
        yield from parse_mail(bmf_path)

# === main ===
def get_cli_option():
    p = argparse.ArgumentParser()
    p.add_argument('mail_box_path', help='specify the directory to *.bmf files.')
    return p.parse_args()

def main():
    opt = get_cli_option()
    mail_box_path = opt.mail_box_path
    for mail, msgid in get_rakuten_pay_mails(mail_box_path):
        print(','.join(map(str,
            [mail.datetime, mail.total, mail.use_point, mail.use_cash, mail.store_name, msgid]
        )))

if __name__ == '__main__':
    main()

