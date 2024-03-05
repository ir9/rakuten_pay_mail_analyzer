from typing import *
import sys
import codecs

# ============================
# decode byte string
# ============================

def _decode_iso2022jp_nkf(b:bytes):
    # require nkf module
    # https://github.com/fumiyas/python-nkf
    import nkf
    return nkf.nkf('-Jw', b).decode('utf-8')

def _decode_iso2022jp_win(b:bytes):
    dec, len = codecs.code_page_decode(50220, b)
    return dec

decode_iso2022jp = _decode_iso2022jp_nkf
if sys.platform == 'win32':
    decode_iso2022jp = _decode_iso2022jp_win

DECODER_MEMO = {}
def decode(b:bytes, encoding:str, ignore_error=False):
    name = DECODER_MEMO.get(encoding)
    if name is None:
        c = codecs.lookup(encoding)
        name = c.name
        DECODER_MEMO[encoding] = name

    if name.startswith('iso2022_jp'):
        # iso2022_jp, iso2022_jp_1, iso2022_jp_2, iso2022_jp_2004, iso2022_jp_3, iso2022_jp_ext
        # python で cp50220, cp50221 がサポートされてればなぁ…
        return decode_iso2022jp(b)

    if name.startswith('shift_jis'):
        # shift_jis_2004, shift_jisx0213
        encoding = 'cp932'
    return b.decode(encoding, errors='ignore' if ignore_error else 'strict')

