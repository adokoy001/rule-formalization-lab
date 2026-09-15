# 原文package仕様 v0.1

更新: 2026-09-15。実装は `rulekernel/source_model.py`、`source_package.py`、`source_checker.py`。

## 目的と保証範囲

自然文の原文を形式化する前に、**どの取得物の、どの版の、どの構造位置を読んだか**を固定する。capture specを外部の期待入力、source packageを保存結果として分離し、`verify-source`が通信せずraw bytesから抽出文と全source unitを再構成する。

`VERIFIED`が確認するもの:

- capture specがpinしたraw/metadataのSHA-256と保存bytesの一致。
- 版付き抽出profileによるUTF-8 XMLから抽出文への決定的な変換。
- 選択した全source unitの順序、構造path、revision-local ID、コードポイントspan、本文。
- retrieval、raw、metadata、抽出文、unit manifest、package lockのhash chain。
- 保存後のoffline再検査。

`--expected-bundle-sha256`を指定した検査では、別に控えた`bundle.lock.json`のSHA-256とも一致することを確認し、結果の`bundle_hash_anchored`をtrueにする。これは、そのhashを記録した時点から取得記録を含むlockが変わっていないことの検査である。取得時刻が真実であることや第三者timestampを証明する署名ではない。

外部hashを指定しない`VERIFIED`では、raw・metadata・派生物とcapture specの対応は再構成するが、`retrieval.json`とlockを一緒に再hashした自己整合な書換えは識別できない。この場合は`bundle_hash_anchored=false`であり、`retrieved_at`、取得mode、HTTP headerを認証済み事実として扱わない。

`VERIFIED`は、取得先が法的に真正であること、取得日時における最新版、法令の適用関係、抽出文の法的意味、後続の形式化が正しいことを保証しない。capture specとpackageを一緒に差し替えれば新しい整合した組になるため、specの採用理由、bundle hash、レビューはpackage外にも記録する。

## capture spec

形式は `rule-source-capture-spec/1`。主な項目は次のとおり。

- `source`: `document_id`、法域、`law_id`、`revision_id`、raw/metadata URL、施行日。
- `expected_raw_sha256`: decodeや改行変換より前のrepresentation body bytesに対するhash。
- `expected_metadata_sha256`: e-Gov `law_data`応答bytesのhash。架空原文ではnull。
- `extraction`: profile、version、profile定義hash。
- `units`: 人が先に選んだ固定分母。`unit_key`、種別、完全な構造path、期待本文。
- `references`: 引用元、原文どおりの文字列、resolved/unresolved、選択済みの参照先。

specのhashはJSONオブジェクトのcanonical表現から計算する。ファイルの字下げ自体はidentityに含めない。未知field、重複key、float/NaN、孤立サロゲート、重複unit、存在しない引用は拒否する。

e-Gov v2では、法域`JP`、非nullの施行日、`article`単位を必須にし、`law_id`だけの暗黙の現行版取得を受け付けない。raw URLを `/api/2/law_file/xml/{revision_id}`、metadata URLを `/api/2/law_data/{revision_id}`へ固定し、metadata内の`law_id`、`law_revision_id`、施行日を照合する。さらにXMLと`law_data`の法令種別、元号年、番号、公布日、法令名を同一法令らしさのsanity checkとして照合する。

XML本体にはrevision IDがないため、このsanity checkだけで同一revisionを証明することはできない。HTTPS取得では同じ明示revision IDを含む二つのURLから得たbodyを別々にそのまま保存し、capture specで両hashを固定する。local importでは、本文とspecを一緒に差し替えた場合まで機械的に真正性を証明できない。

## package構成

```text
bundle/
  bundle.lock.json
  retrieval.json
  raw/
    source.xml
    law-data.json        # e-Govだけ
  derived/
    source.txt
    source-units.json
```

JSON成果物はUTF-8 canonical JSONで保存する。`bundle.lock.json`は自分自身のhashを含めず、各成果物の相対path、bytes、SHA-256、抽出profile、単位数を束ねる。検査結果の`bundle_hash`はlock file bytesのSHA-256である。package内のsymlink、絶対path、追跡されていない追加fileは受理しない。

`retrieval.json`は取得イベントを表し、`retrieved_at`をRFC 3339 UTCで保持する。`effective_from`は法令版のメタデータであり、取得時刻から推論しない。local importはHTTP statusやheaderをnullのまま残す。HTTPS取得は要求URL、最終URL、status、Content-Type/Encoding/Disposition/Lengthの観測値を保存する。

## `xml-unit-text/2`

profile定義hashは `f82a826149862515a881dc34c7ddb6a26f050c11e28d4a73ab3689f60cdf46bc`。

1. raw bytesを先にhashし、変更せず保存する。
2. BOMなしUTF-8としてstrict decodeする。置換文字による復旧はしない。
3. XML 1.0のCRLFとCRを派生textではLFへ正規化する。
4. XMLの定義済み文字参照と数値文字参照をdecodeする。DTD/ENTITY宣言は拒否する。
5. 架空原文の選択unitでは、空白だけのtext/tailも含めてmixed contentをそのまま保持する。
6. e-Govでは`Article`、`Paragraph`、`ParagraphSentence`直下の空白だけのtext/tailに限ってindentationとして除く。同じ位置の空白以外の文字は`UNSUPPORTED`とし、黙って本文へ混ぜない。`ArticleCaption`、`ArticleTitle`、`ParagraphNum`、`Sentence`内の空白は保持する。
7. `Ruby`は非空の基底textと、直下の非空なleaf `Rt`一つだけを受け付ける。基底文字は残し、その`Rt`の読みだけを除く。Ruby外の`Rt`、複数`Rt`、入れ子、読みの後のtailは`UNSUPPORTED`。
8. UnicodeのNFC/NFKC等は行わない。
9. 各unitの間へLFを一つだけ入れる。

現在のe-Gov profileは、本則 `MainProvision`内の`Article`を完全な構造pathで選ぶ小さな版である。選択Article内はcaption/title/paragraph/sentence/Rubyに限定し、号、表、図、数式、引用構造等を含む未知構造は黙って落とさず`UNSUPPORTED`にする。必要になった時点でfixtureと新しいprofile/versionを追加する。

## source unit

`derived/source-units.json`の各行は、次を持つ。

- 0から連続する`index`と人向け`unit_key`。
- `document_id`、`revision_id`、構造種別、完全な構造pathから決定的に作る`source_unit_id`。
- `start_codepoint`を含み`end_codepoint`を含まないUnicode code point範囲。
- exact text、そのUTF-8 SHA-256、前後最大16 codepoint。

同じ文が複数回あっても、最初の文字列一致をanchorにしない。構造pathとsibling ordinalで別単位にする。unitはrevision-localであり、別版の同じ条番号と自動的に同一視しない。選択順はXMLのpreorderと同じで、親子を同時に選ぶ重複範囲も受理しない。

checkerはcapture specを固定分母としてrawから全行を再生成する。package内の`unit_count`やhashだけを相互照合する方式ではないため、unitの欠落、複製、並替え、同文pathの入替え、UTF-8 byte/UTF-16 unitとコードポイントの混同を拒否できる。

## CLIと終了コード

```bash
python3 -m rulekernel source-build SPEC RAW \
  --metadata LAW_DATA_JSON \
  --retrieved-at 2026-09-15T10:00:00Z \
  --bundle NEW_DIRECTORY

python3 -m rulekernel source-fetch-egov SPEC --bundle NEW_DIRECTORY
python3 -m rulekernel verify-source SPEC BUNDLE \
  --expected-bundle-sha256 EXTERNALLY_RECORDED_LOCK_SHA256
```

`source-build`は保存済みbytesのlocal import、`source-fetch-egov`はspecがpinした二つのHTTPS URLの明示取得、`verify-source`は完全offline検査である。生成系は同じ親directoryのstagingへ全成果物を書き、独立checkerの合格後だけatomic no-replaceで新規destination名へ公開する。既存destinationを上書きしない。raw取得後にmetadata取得が失敗した場合も、新packageを公開せず、古いpackageを今回の成功として返さない。

v0.1の新規directory公開はLinuxの`renameat2(RENAME_NOREPLACE)`を使う。WSLでは`/home`等のLinux filesystemを対象とし、DrvFSの`/mnt/c`はこの原子性を提供しないため`UNSUPPORTED`で停止する。Windows native Pythonでは既存destinationを拒否する`os.rename`を使う。それ以外のOS/filesystemへ安全性を推測してfallbackしない。

- exit 0: package整合、未解決参照0。
- exit 1: package整合、構造化して残した未解決参照あり。
- exit 2: 入力不正、版/hash/抽出不一致、未対応、取得失敗、上限、I/O失敗で未確定。

source用上限はraw 16 MiB、metadata 4 MiB、spec 4 MiB、manifest 8 MiB、unit/reference各4,096、XML node 100,000、深さ128。有限モデルと証拠の上限とは別契約である。

## 保存例

- [Unicode架空原文](../examples/sources/fictional-unicode/): 絵文字、結合文字、XML文字参照、同文反復、Ruby、未解決参照を含む。
- [刑法41条snapshot](../examples/sources/penal-code-41/): 刑法 `140AC0000000045` の明示版 `140AC0000000045_20260521_507AC0000000039`について、全文XMLと`law_data`を保存し、本則41条を完全な構造pathで選択した。
- [T04検証記録](verification-t04-2026-09-15.md): bytes、hash、取得時刻、テスト、残る境界。

公式API仕様は[e-Gov法令API v2](https://laws.e-gov.go.jp/api/2/swagger-ui)、構造の参考は[法令標準XMLスキーマ解説](https://laws.e-gov.go.jp/docs/law-data-basic/419a603-xml-schema-for-japanese-law/)を確認した。JSON形式本文は公式にも試行版とされているため、規範的なraw本文はXML file応答を保存する。
