from typing import *
import sys
import argparse
import email

import rakuten_pay_mail_parser

def _main():
    p = argparse.ArgumentParser()
    p.add_argument("email_path")
    opt = p.parse_args()

    email_path = opt.email_path
    with open(email_path, "rb") as h:
        mail = email.message_from_binary_file(h)
    pay_mail = rakuten_pay_mail_parser.parse_email(mail)
    print(pay_mail)

if __name__ == '__main__':
    _main()

