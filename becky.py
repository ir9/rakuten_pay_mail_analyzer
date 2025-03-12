from typing import *
import sys
import io
import csv
import datetime
import traceback
import os.path
import glob
import argparse
import contextlib
import email
import email.message

join_path = os.path.join

import rakuten_pay_mail_parser as r_pay

class CLIParameter(NamedTuple):
    mailbox_path: str
    since: Optional[datetime.datetime]
    until: Optional[datetime.datetime]
argv = None

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

# =====================================
# for Folder.idx
# =====================================

"""
dwBodyPtr        このメールアイテムのbmfファイル中の先頭からの位置
dwMsgID                このメールアイテムをフォルダ中でユニークに識別する為のDWORD値
dwFileName        bmfファイルのファイル名部分
strSubject        メールの件名
strFrom                メールの差出人
strTo                メールの宛先
strMsgId        メールのMessage-Idフィールド
strReferences        メールの参照先のMessage-Id（In-Reply-To, Referenceフィールドから取得）
tSend                メールの送信日時（C言語のtime_t値）（Dateフィールドより取得）
tRecv                メールの配信日時（C言語のtime_t値）（Received フィールドより取得）
tDnld                メールの受信日時（C言語のtime_t値）（受信時に決定）
dwSize                メールのサイズ（バイト数）
dwStatus        メールのステータスフラグ
                下位ビットより以下の意味を持ちます。
                0x00000001 既読
                0x00000002 転送済み
                0x00000004 返信済み
                0x00000008 添付あり（Content-Typeがmultipartヘッダである）
                0x00000020 スレッド表示で、下位のメッセージを閉じた状態（スレッドの最上位メッセージでのみ有効）
                0x00000040 スレッド表示で、下位にメッセージを持つ
                0x00000080 スレッド表示で、下位に未読メッセージを持つ
                0x00000100 分割メッセージ(message/partial)の一部
                0x00000200 Resentヘッダにより転送されたメッセージ
                0x00000400 MDN処理済み（開封通知の送信に同意してもしなくてもビットが立つ）
                これ以外のビットは未使用か予約済みのため、常に０
                0x00001000 フラグつき
                0x00002000 HTML形式
                0x00010000 宛先に自分のメールアドレスが含まれる（v2.24)
                0x00020000 Ccに自分のメールアドレスが含まれる（v2.24)
nColor                カラーラベルのCOLORREF値
nPriority        ５段階の重要度
dwParentID        スレッド表示の際の親アイテムのdwMsgID
strCharSet        このメールのキャラクタセット（空でも可）
str                テンポラリ文字列（内容は不定、通常空）
strExtAtch        (v2.05より）添付ファイルを別ファイルに保存している場合、
                その添付ファイルのファイル名部分。複数ある場合は "/" で
                区切られる。
"""

class FolderIdxEntity(NamedTuple):
    dwBodyPtr: int  #このメールアイテムのbmfファイル中の先頭からの位置
    dwMsgID: str    #このメールアイテムをフォルダ中でユニークに識別する為のDWORD値
    dwFileName: str # bmfファイルのファイル名部分
    strSubject: str #メールの件名
    strFrom: str #メールの差出人
    strTo: str #メールの宛先
    strMsgId: str #メールのMessage-Idフィールド
    strReferences: str #メールの参照先のMessage-Id（In-Reply-To,: int #Referenceフィールドから取得）
    tSend: datetime.datetime #メールの送信日時（C言語のtime_t値）（Dateフィールドより取得）
    tRecv: datetime.datetime #メールの配信日時（C言語のtime_t値）（Received: int #フィールドより取得）
    tDnld: datetime.datetime #メールの受信日時（C言語のtime_t値）（受信時に決定）
    dwSize: int #メールのサイズ（バイト数）
    dwStatus: str #メールのステータスフラグ
    nColor: str #カラーラベルのCOLORREF値
    nPriority: int #５段階の重要度
    dwParentID: str #スレッド表示の際の親アイテムのdwMsgID
    strCharSet: str #このメールのキャラクタセット（空でも可）
    str_: str #テンポラリ文字列（内容は不定、通常空）
    strExtAtch: str # (v2.05より）添付ファイルを別ファイルに保存している場合

def _load_folder_idx(folder_idx_path:str):
    def _load():
        with open(folder_idx_path, 'rb') as h:
            return h.read()

    def s(b:bytes, encoding='ascii'):
        return b.decode(encoding)
    
    def to_date(b:bytes):
        num = int(b, 16)
        return datetime.datetime.fromtimestamp(num)

    DECODE_MAP = {
        'iso-2022-jp': 'cp932',
    }
    def decode(s: bytes, encoding:str):
        charset = DECODE_MAP.get(encoding.lower(), encoding)
        try:
            return s.decode(charset, errors='ignore')
        except LookupError as ex:
            for charset in ['cp932', 'utf-8']:
                with contextlib.suppress(UnicodeDecodeError):
                    return s.decode(charset)
            raise

    def _parse(line:bytes):
        cells = line.split(b'\x01')
        char_set = s(cells[16]) # str #このメールのキャラクタセット（空でも可）

        # print(len(cells))
        # print(cells)
        return FolderIdxEntity(
            int(cells[0], 16),  # int  #このメールアイテムのbmfファイル中の先頭からの位置
            s(cells[1]), # str    #このメールアイテムをフォルダ中でユニークに識別する為のDWORD値,
            s(cells[2]), # str # bmfファイルのファイル名部分,
            decode(cells[3], char_set), # str #メールの件名
            decode(cells[4], char_set), # str #メールの差出人
            decode(cells[5], char_set), # str #メールの宛先
            s(cells[6]), # str #メールのMessage-Idフィールド
            s(cells[7]), # str #メールの参照先のMessage-Id（In-Reply-To, Referenceフィールドから取得）
            to_date(cells[8]),  # datetime.datetime #メールの送信日時（C言語のtime_t値）（Dateフィールドより取得）
            to_date(cells[9]),  # datetime.datetime #メールの配信日時（C言語のtime_t値）（Received フィールドより取得）
            to_date(cells[10]), # datetime.datetime #メールの受信日時（C言語のtime_t値）（受信時に決定）
            int(cells[11], 16), # int #メールのサイズ（バイト数）
            s(cells[12]), # int #メールのステータスフラグ
            s(cells[13]), # str #カラーラベルのCOLORREF値
            int(cells[14]), # int #５段階の重要度
            s(cells[15]), # str #スレッド表示の際の親アイテムのdwMsgID
            char_set, #cells[16], # str #このメールのキャラクタセット（空でも可）
            s(cells[17]), # str #テンポラリ文字列（内容は不定、通常空）
            decode(cells[18], char_set) # str # (v2.05より）添付ファイルを別ファイルに保存している場合
        )

    idx_file = _load()
    lines = idx_file.splitlines()
    return [ _parse(line) for line in lines[1:] ]

def _fitler_idx_entity(entities: List[FolderIdxEntity], since: Optional[datetime.datetime], until: Optional[datetime.datetime]):
    if since is None and until is None:
        return entities

    if since is None:
        since = datetime.datetime.min

    if until is None:
        until = datetime.datetime.max
    else:
        until = until + datetime.timedelta(days=1)

    def is_include(e: FolderIdxEntity):
        return since <= e.tSend <= until

    return list(filter(is_include, entities))

# =====================================
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
                    if pay_mail.has_error:
                        raise r_pay.UnexcpectedRakutenPayMailException() 
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
    def enumerate_bmf_files(idx_filepath: str):
        print(f"found: {idx_filepath}", end='', file=sys.stderr)
        idx_fullpath = join_path(mail_box_path, idx_filepath)
        entities = _load_folder_idx(idx_fullpath)
        entities = _fitler_idx_entity(entities, argv.since, argv.until)
        print(f' / {len(entities)} entities', file=sys.stderr)

        dir_name          = os.path.dirname(idx_fullpath)
        bmf_filename_list = set(e.dwFileName for e in entities)
        return [ join_path(mail_box_path, dir_name, f"{bmf_filename}.bmf") for bmf_filename in bmf_filename_list ]

    folder_idx_list = glob.glob('**/Folder.idx', root_dir=mail_box_path, recursive=True)
    files           = sum(map(enumerate_bmf_files, folder_idx_list), [])
    file_count      = len(files)

    for i, bmf_file in enumerate(files):
        basename = os.path.basename(bmf_file)
        print(f'{basename} ({i}/{file_count})', file=sys.stderr, flush=True)
        bmf_path = os.path.join(mail_box_path, bmf_file)
        yield from parse_mail(bmf_path)

# === main ===
def get_cli_option():
    p = argparse.ArgumentParser()
    p.add_argument('mail_box_path', help='specify the directory to *.bmf files.', type=str)
    p.add_argument('-s', '--since', help='ex) 2025-01-01', type=str)
    p.add_argument('-u', '--until', help='ex) 2025-01-01', type=str)
    return p.parse_args()

def _parse_date(d: str):
    if d is None:
        return None
    return datetime.datetime.strptime(d, "%Y-%m-%d")

def main():
    opt = get_cli_option()
    mail_box_path = opt.mail_box_path
    date_since = _parse_date(opt.since)
    date_until = _parse_date(opt.until)

    global argv
    argv = CLIParameter(mail_box_path, date_since, date_until)

    outbuff = io.StringIO()
    writer  = csv.writer(outbuff, lineterminator='\n', quoting=csv.QUOTE_NONNUMERIC)
    writer.writerow(r_pay.RakutenPayMail.CSV_VALUE_HEADER)
    writer.writerows(mail.csv_rawvalues() for mail in get_rakuten_pay_mails(mail_box_path))
    print(outbuff.getvalue())

if __name__ == '__main__':
    main()

