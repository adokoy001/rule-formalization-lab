# 第三者由来データとライセンスの状態

## プロジェクト本体

このリポジトリのうち、本プロジェクトが作成したコード、文書、架空fixtureは
[MIT License](LICENSE)で提供する。著作権表示は`Copyright (c) 2026 adokoy001`。

次に列挙するraw・derived各4ファイル、合計8ファイルは、e-Govから取得又は抽出した
法令本文の主な保存先である。これらの法令本文と、その全部又は一部を
`source-spec.json`、candidate、compiled artifact、binding、調査文書その他のファイルへ
再掲した部分は、本プロジェクトからMITとして再許諾しない。e-Govの利用規約、PDL1.0、
その他の適用法令・権利条件に従う。

取得・抽出・検査のため本プロジェクトが作成したコード、ファイル構造、hash、判断、説明などは
MIT Licenseの対象である。ただし、それらのファイル内に含まれる法令本文そのものは上記の
扱いとする。以下の一覧は法令本文を含む全ファイルの網羅表ではなく、一次保存物の一覧である。

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

取得日時は`2026-09-15T12:13:54Z`。`raw/`の2ファイルは取得した応答bytes、`derived/`の
2ファイルは本プロジェクトの`xml-unit-text/2` profileで本則41条を抽出・加工したもの。

## e-Gov法令API由来の刑事訴訟法snapshot

次のファイルは、e-Gov法令API v2から取得した刑事訴訟法の版
`323AC0000000131_20260813_508AC0000000067`に由来する。

- `examples/sources/criminal-procedure-55-203-206/bundle/raw/source.xml`
- `examples/sources/criminal-procedure-55-203-206/bundle/raw/law-data.json`
- `examples/sources/criminal-procedure-55-203-206/bundle/derived/source.txt`
- `examples/sources/criminal-procedure-55-203-206/bundle/derived/source-units.json`

出典:

- [e-Gov法令API v2・法令XML](https://laws.e-gov.go.jp/api/2/law_file/xml/323AC0000000131_20260813_508AC0000000067)
- [e-Gov法令API v2・法令metadata](https://laws.e-gov.go.jp/api/2/law_data/323AC0000000131_20260813_508AC0000000067)

取得日時は`2026-09-16T05:05:44Z`。`raw/`の2ファイルは取得した応答bytes、`derived/`の
2ファイルは同profileで55条・203条・204条・205条・206条を抽出・加工したもの。

共通の利用条件:

- [e-Govポータル利用規約](https://www.e-gov.go.jp/terms)
- [公共データ利用規約（第1.0版、PDL1.0）](https://www.digital.go.jp/resources/open_data/public_data_license_v1.0)

取得URL、HTTP記録、hash、抽出位置は各bundle内の`retrieval.json`と`bundle.lock.json`に
保存している。本プロジェクトによる形式化、抽出、解釈又は検証結果は、デジタル庁、e-Gov、
裁判所その他の公的機関が作成・承認したものではない。
