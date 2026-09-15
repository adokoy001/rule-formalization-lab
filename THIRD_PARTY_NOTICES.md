# 第三者由来データとライセンスの状態

## プロジェクト本体

このリポジトリのうち、本プロジェクトが作成したコード、文書、架空fixtureは
[MIT License](LICENSE)で提供する。著作権表示は`Copyright (c) 2026 adokoy001`。

次に列挙するe-Gov由来の4ファイルは、本プロジェクトのMIT Licenseの適用対象外とし、
本プロジェクトからMITとして再許諾しない。これらにはe-Govの利用規約、PDL1.0、
その他の適用法令・権利条件が適用される。

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
- [公共データ利用規約（第1.0版、PDL1.0）](https://www.digital.go.jp/resources/open_data/public_data_license_v1.0)

取得日時は`2026-09-15T12:13:54Z`。`raw/`の2ファイルは取得した応答bytesを保存したもの、
`derived/`の2ファイルは本プロジェクトの`xml-unit-text/2` profileで本則41条を抽出・加工して
作成したもの。取得URL、HTTP記録、hash、抽出位置は同bundle内の`retrieval.json`と
`bundle.lock.json`に保存している。

本プロジェクトによる形式化、抽出、解釈又は検証結果は、デジタル庁又はe-Govが作成・承認した
ものではない。
