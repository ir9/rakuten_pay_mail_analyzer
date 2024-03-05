# rakuten_pay_mail_analyzer
parser for rakuten pay notification mail


# nkf の install

このパッケージの windows 環境での install に躓いたのでメモ

## 問題

pip install nkf すると make が走りますが io.h が無いと怒られます

```
fatal error C1083: include ファイルを開けません。'io.h':No such file or directory
```

## 解決

お使いの pythonのビルドplatform (x64とか) と同じ開発者プロンプトを開き環境変数を設定します

- set include=%4include%;C:\Program Files (x86)\Windows Kits\10\Include\${SDK_VERSION}\ucrt
- set lib=%lib%;C:\Program Files (x86)\Windows Kits\10\Lib\${SDK_VERSION}\ucrt\x64

後に pip install nkf するとビルドが通ります

## 解説

s-jis 的には機種依存文字であるが cp932 には入ってる "Ⅶ" などの文字が
メールのヘッダー等に入ってくるかも知れません。
s-jis の MS方便 である cp932 なら解釈出来ますが
メールは iso-2022-jp (jis) が使われるため cp50220 / cp50221 が必要になります。

しかし python は cp50220 / cp50221 をサポートしていません！
→ nkf パッケージが必要になります。


