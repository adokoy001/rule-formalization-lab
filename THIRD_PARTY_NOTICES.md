# 第三者由来データとライセンスの状態

## プロジェクト本体

2026-09-16時点では、このリポジトリのコード、文書、架空fixtureに対する
オープンソースライセンスを選択していない。公開リポジトリとして閲覧できること自体は、
適用法令又はGitHubの利用条件を超える再利用許諾を意味しない。

ライセンスを後から追加する場合も、次の第三者由来データにはそのライセンスを一律に
適用しない。

## e-Gov法令API由来の刑法snapshot

次のファイルは、e-Gov法令API v2から取得した刑法の版
`140AC0000000045_20260521_507AC0000000039`に由来する。

- `examples/sources/penal-code-41/bundle/raw/source.xml`
- `examples/sources/penal-code-41/bundle/raw/law-data.json`
- `examples/sources/penal-code-41/bundle/derived/source.txt`
- `examples/sources/penal-code-41/bundle/derived/source-units.json`

出典:

- [e-Gov法令API v2・法令XML](https://laws.e-gov.go.jp/api/2/law_file/xml/140AC0000000045_20260521_507AC0000000039)
- [e-Gov法令API v2・法令metadata](https://laws.e-gov.go.jp/api/2/law_data/140AC0000000045_20260521_507AC0000000039)
- [e-Govポータル利用規約](https://www.e-gov.go.jp/terms)

取得日時は`2026-09-15T12:13:54Z`。`raw/`の2ファイルは取得した応答bytesを保存したもの、
`derived/`の2ファイルは本プロジェクトの`xml-unit-text/2` profileで本則41条を抽出・加工して
作成したもの。取得URL、HTTP記録、hash、抽出位置は同bundle内の`retrieval.json`と
`bundle.lock.json`に保存している。

本プロジェクトによる形式化、抽出、解釈又は検証結果は、デジタル庁又はe-Govが作成・承認した
ものではない。
