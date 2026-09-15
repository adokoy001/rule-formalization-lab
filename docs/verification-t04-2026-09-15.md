# T04 原文package検証記録

実施日: 2026-09-15。対象: [`rule-source-package/1`](source-package-v0.1.md)。これは原文snapshotのbytes・抽出・構造位置を検査した記録であり、刑法41条の法的意味や整合性を判定した記録ではない。

## 実装した経路

- capture specの厳密検査とcanonical hash: [`source_model.py`](../rulekernel/source_model.py)
- local import、e-Gov HTTPS取得、staging生成: [`source_package.py`](../rulekernel/source_package.py)
- producerをimportせずrawから再抽出するoffline checker: [`source_checker.py`](../rulekernel/source_checker.py)
- `source-build`、`source-fetch-egov`、`verify-source`: [`__main__.py`](../rulekernel/__main__.py)

有限Core `finite-decisions/1`へsource fieldを追加していない。既存モデルとT01〜T03の保存証拠も変更していない。

## 架空Unicode原文

保存先: [`examples/sources/fictional-unicode`](../examples/sources/fictional-unicode/)

| 項目 | 実測 |
|---|---|
| raw | 271 bytes / `975492dd0211c55b50221ea2ccdd1ce0aa03fde025efb9434350df7cd5cfac11` |
| 抽出text | 126 bytes / `80bef49086f25a93976395e9c165de605eba4fb2793110ccec3b2fc79e037edd` |
| source unit manifest | 2,077 bytes / `8752a6eb2a062598789f4436cbd91372f03303e0ab37d245e4654b297cb42a57` |
| bundle lock / bundle hash | 1,053 bytes / `baeba5fb46ac6fb33aa5a31983ea58ab9d2a484cc26222dec256fb26f27bec50` |
| capture spec hash | `fd70f7c42184cc333cbbe03d0903353f812de7e3e36b4182526c3d74c5fe62a8` |
| 原文単位 | 3 |
| codepoint spans | U1 `[0,18)`、U2 `[19,37)`、U3 `[38,54)` |
| 未解決参照 | 1: U3の「別に定める」 |

U1/U2は同じ本文断片を含むが、構造pathから異なるsource unit IDになった。`👩‍⚖️`のZWJ sequenceと`e + U+0301`を正規化せず保持し、`&amp;`は派生textで`&`、`<Ruby>賭<Rt>と</Rt></Ruby>`は`賭`になった。未解決参照を隠さないため、生成・再検査は`VERIFIED`でexit 1。

## e-Gov刑法41条snapshot

保存先: [`examples/sources/penal-code-41`](../examples/sources/penal-code-41/)

- 法令ID: `140AC0000000045`
- 明示版: `140AC0000000045_20260521_507AC0000000039`
- metadata上の施行日: `2026-05-21`
- 取得記録値: `2026-09-15T12:13:54Z`（日本時間21:13:54）
- 選択path: `/Law[1]/LawBody[1]/MainProvision[1]/Part[1]/Chapter[7]/Article[7]`
- source unit ID: `d7e82dbc6df76bb2ae495e8de02aaf979eb907838c771dc47e550fbabbba23b7`
- span: `[0,30)` codepoints

| 成果物 | bytes | SHA-256 |
|---|---:|---|
| `raw/source.xml` | 379,661 | `2b079c84c131b571974a36e1c87589c5a4737a037c309caf1ec07fa4d12feedb` |
| `raw/law-data.json` | 393,472 | `e24b142ceb4b7a748a16835de49870fe9672165fdf0e66358b05004bdf8689a0` |
| `derived/source.txt` | 90 | `ddc66485d00c724a12f41c746ab52ae4c2c668259bfb7fe1a2d0bf425413ea5d` |
| `derived/source-units.json` | 1,098 | `677889a47e93aafd05ec692fd20e247e90b939f4619eaaadb422b37c64ff8337` |
| `retrieval.json` | 847 | `fcfa0a543876f56df042725a32ec707f058f154fc3f56911899d1daa07563f06` |
| `bundle.lock.json` | 1,186 | `60da7e094d2a8a7d5b1dbb7addf93e9af5ff573fa6cc56f430b499e7b9003060` |

capture spec hashは `0ba24f19e403e37fc62775516d3363f8640af6a0a0a134085d27980cbc91b6b8`。抽出profileは`xml-unit-text/2`、定義hashは`f82a826149862515a881dc34c7ddb6a26f050c11e28d4a73ab3689f60cdf46bc`。取得したXMLには`Num="41"`のArticleが本則と附則側に少なくとも二つある。本則を含む完全pathと期待本文をpinし、附則側を誤抽出しないことを小型fixtureでもテストした。

XMLと`law_data`の法令種別、元号年、番号、公布日、法令名も照合した。これは同じ法令らしさのsanity checkであり、XML本文にrevision IDがない以上、同一revisionの暗号学的証明ではない。今回のnetwork取得では、同じ明示revision IDを含む二つのURLから取得したbody hashがcapture specと一致した。

実行:

```bash
python3 -m rulekernel source-fetch-egov \
  examples/sources/penal-code-41/source-spec.json \
  --bundle examples/sources/penal-code-41/bundle --json

python3 -m rulekernel verify-source \
  examples/sources/penal-code-41/source-spec.json \
  examples/sources/penal-code-41/bundle \
  --expected-bundle-sha256 60da7e094d2a8a7d5b1dbb7addf93e9af5ff573fa6cc56f430b499e7b9003060 \
  --json
```

最初の取得と公開はexit 0。後者はsocketを失敗させた状態でも保存物だけから再検査でき、同じbundle hash、raw hash、unit manifest hashと`bundle_hash_anchored=true`を返した。

## 負例と回帰

`python3 -m unittest discover -s tests -q`で**159テスト合格**。既存124件にT04の35件を追加した。

追加した主な固定例:

- CRLF、XML文字参照、ZWJ絵文字、結合文字、同文反復、Ruby/Rt。本文中のASCII/U+3000空白を保持し、block indentationだけを除く。
- 本則41条と附則41条の同番号、間違ったquote/path、逆順、親子の重複選択。
- 不正UTF-8、BOM、非UTF-8宣言、DTD/ENTITY、未知field/profile hash、版URL不一致。
- Ruby外`Rt`、壊れたRuby、e-Gov block直下の本文、null施行日、誤った法域/単位種別、XMLとmetadataの法令名不一致。
- raw、抽出text、unit manifest、retrieval、lockの個別改ざん。retrievalとlockを自己整合に書き換えた場合も、元の外部bundle hash指定で拒否。
- unit削除、複製、並替え、codepoint endのoff-by-one、別revision package差替え、追加file、file/directory symlink。
- 注入transportによる二応答の正常取得、実API同様にContent-Lengthがない応答、二本目timeout、Content-Length不一致、既存destination非上書き。
- checker/rename失敗時のstaging掃除、公開直前にdestinationが競合生成されるrace、no-replace非対応filesystemの安全停止。
- CLIの保存→offline再検査、外部bundle hash照合、未解決参照のexit 1、失敗時`published_bundle=null`、NaN/無限timeout拒否。
- repositoryに保存した架空・刑法の両packageそのものを、networkを失敗させた状態で固定外部hashと照合する回帰。

取得失敗試験では、raw取得後にmetadata取得を失敗させ、新destinationが存在しないことと、既存の成功package全fileがbyte-for-byte不変であることを確認した。live APIは通常のunit testへ依存させていない。

## 残る境界

- capture specの選択とexpected hash自体の正しさは、人の取得・レビュー記録に依存する。bundle hashを指定しても取得時刻の真実性や発行者を証明する署名・第三者timestampにはならない。
- `xml-unit-text/2`のe-Gov対象は本則の単純なArticle。号、表、図、数式、`QuoteStruct`等を含む条文は新profileとfixtureが必要。
- XML/metadataの法令同一性field照合はrevision bindingではない。local importで本文・specを一緒に差し替える場合の真正性は外部レビューに残る。
- 原子的な新規directory公開はWSLのLinux filesystemで検証した。`/mnt/c`ではno-replaceを保証できないため`UNSUPPORTED`で停止する。
- 全文XMLは保存したが、source unitの固定分母は今回選んだ本則41条の1単位。法令全条の構造棚卸し完了ではない。
- 参照の自動発見、解釈IR、原文→Core来歴、意味レビュー、法的推論は未実装。次はT05の手書きIRで、このunit manifest hashを外部入力として結ぶ。
