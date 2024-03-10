from typing import *
import argparse
import quopri
import base64
import email
import email.message

import util

TRANS_DECODE_MAP:dict[str, Callable[[Any], bytes]] = {
    'base64':           base64.b64decode,
    'quoted-printable': quopri.decodestring,
    '7bit':             quopri.decodestring,
}
def _dump_mail_body(msg:email.message.Message):
    charset        = msg.get_content_charset()
    trans_encoding = msg['Content-Transfer-Encoding']
    # print(f"{charset} / {trans_encoding}")
    raw_body = msg.get_payload()

    body = TRANS_DECODE_MAP[trans_encoding](raw_body)
    return util.decode(body, charset)

def _content_type_is_text_plain(part:email.message.Message):
    return part.get_content_type() == 'text/plain'

def _main():
    p = argparse.ArgumentParser()
    p.add_argument("email_path")
    opt = p.parse_args()

    email_path = opt.email_path
    with open(email_path, "rb") as h:
        mail = email.message_from_binary_file(h)
    
    for i, msg in enumerate(filter(_content_type_is_text_plain, mail.walk())):
        filename = f"{email_path}.{i:02}.txt"
        body = _dump_mail_body(msg)
        with open(filename, "w", encoding='utf-8') as h:
            print(body, file=h, end="")

if __name__ == '__main__':
    _main()


