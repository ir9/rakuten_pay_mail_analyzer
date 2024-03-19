from typing import *
import sys
import io
import csv
import traceback
import os.path
import glob
import argparse
import email
import email.message

import rakuten_pay_mail_parser as r_pay

def _dump_mail(mail:email.message.Message, msg:str, filename:str):
    # dump a raw mail stream
    with open(f"{filename}.mail.txt", "wb") as h:
        h.write(bytes(mail))

    with open(f"{filename}.info.txt", "w", encoding='utf-8') as h:
        print(msg, file=h, end='')

def _dump_exception(ex:r_pay.UnexcpectedRakutenPayMailException):
    stack_list = (ex.stack_trace_list or []) + [traceback.format_exc()]
    rec = [
        f"from: {ex.from_}",
        f"subject: {ex.subject}",
        f"msgid: {ex.msgid}",
        "",
        f"{ex.mail_body}",
        "--------",
        '--------'.join(stack_list),
    ]
    return '\n'.join(rec)

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
            try:
                mail  = email.message_from_bytes(mail_raw)
                msgid = mail['Message-ID']

                pay_mail = r_pay.parse_email(mail)
                if pay_mail:
                    yield pay_mail
            except r_pay.UnexcpectedRakutenPayMailException as ex:
                basename = os.path.basename(bmf_path)
                w(f'Unexpected rakute pay mail format:{basename}:{msgid}:{traceback.format_exc()}')

                # remove invalid chars in windows path
                for c in '\\/:*?"<>|':
                    msgid = msgid.replace(c, '')
                _dump_mail(mail_raw, _dump_exception(ex), f"{basename}_{msgid}")
                continue
    except Exception as ex:
        print(f"{bmf_path}:{msgid}:{ex}")
        raise

def get_rakuten_pay_mails(mail_box_path:str):
    files = glob.glob('**/*.bmf', root_dir=mail_box_path, recursive=True)
    file_count = len(files)
    for i, bmf_file in enumerate(files):
        basename = os.path.basename(bmf_file)
        print(f'{basename} ({i}/{file_count})', file=sys.stderr, flush=True)
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

    outbuff = io.StringIO()
    writer  = csv.writer(outbuff, lineterminator='\n', quoting=csv.QUOTE_NONNUMERIC)
    writer.writerow(r_pay.RakutenPayMail.CSV_VALUE_HEADER)
    writer.writerows(mail.csv_rawvalues() for mail in get_rakuten_pay_mails(mail_box_path))
    print(outbuff.getvalue())

if __name__ == '__main__':
    main()

