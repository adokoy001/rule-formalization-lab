# 原文packageの保存例

T04で、形式モデルとは別に原文のbytes・版・抽出位置を固定した例。仕様は[原文package v0.1](../../docs/source-package-v0.1.md)、実測は[T04検証記録](../../docs/verification-t04-2026-09-15.md)にある。

## 架空Unicode原文

`fictional-unicode/`には、絵文字、結合文字`e + U+0301`、XML文字参照、同文反復、`Ruby/Rt`、未解決の「別に定める」を含む。packageは整合しているが未解決参照1件を保持するため、再検査のexitは1。

```bash
python3 -m rulekernel verify-source \
  examples/sources/fictional-unicode/source-spec.json \
  examples/sources/fictional-unicode/bundle \
  --expected-bundle-sha256 baeba5fb46ac6fb33aa5a31983ea58ab9d2a484cc26222dec256fb26f27bec50
```

## 星見クラブ資料形式

`handbook-scope/`にはClub20 fixedの第19条・第20条と同じ架空原文を2単位として保存した。第20条の「第19条」はresolved referenceである。[手書き解釈fixture](../interpretations/handbook-scope/README.md)がこのpackageをCoreへ変換し、T03.1の段階別到達可能性とscope期待を外部hash付きで照合する。

```bash
python3 -m rulekernel verify-source \
  examples/sources/handbook-scope/source-spec.json \
  examples/sources/handbook-scope/bundle \
  --expected-bundle-sha256 52ca5a149fe1e901b62854ac4b12c613e0ab8261e54a4b6a932f2963bd0dc8e4
```

## 架空会員規約

`member-eligibility/`には、登録者の18歳境界と利用停止の例外を2原文単位として保存した。第2条の「前条」から第1条へのresolved referenceをmanifestに明記している。T05の[手書き解釈fixture](../interpretations/member-eligibility/README.md)はこのpackageを外部入力として使い、十分条件のdecision 1件とreplacement exception 1件へ変換する。

```bash
python3 -m rulekernel verify-source \
  examples/sources/member-eligibility/source-spec.json \
  examples/sources/member-eligibility/bundle \
  --expected-bundle-sha256 a63021f7766381a75a7cb8b91f285f47122c1f5d3912a2f6132653e91cf4ac32
```

これらの原文自体は架空で、reviewもCodexが作った開発fixtureである。実在規約の意味対応や専門家確認を表さない。

## 刑法41条

`penal-code-41/`には、e-Gov法令API v2から2026-09-15に取得した次の二つの応答と、抽出した本則41条を保存した。

- XML: `law_file/xml/140AC0000000045_20260521_507AC0000000039`
- metadata: `law_data/140AC0000000045_20260521_507AC0000000039`

XMLには本則以外にも`Num="41"`のArticleがあるため、条番号検索だけを使わず、`/Law[1]/LawBody[1]/MainProvision[1]/Part[1]/Chapter[7]/Article[7]`を指定した。再検査は通信しない。

```bash
python3 -m rulekernel verify-source \
  examples/sources/penal-code-41/source-spec.json \
  examples/sources/penal-code-41/bundle \
  --expected-bundle-sha256 60da7e094d2a8a7d5b1dbb7addf93e9af5ff573fa6cc56f430b499e7b9003060
```

指定値は各`bundle.lock.json`のSHA-256をpackage外の記録として使う例。省略してもrawからの再構成は行うが、取得記録とlockを一緒に再hashした書換えは識別できず、結果の`bundle_hash_anchored`はfalseになる。

再取得は既存bundleを上書きせず、WSLのLinux filesystem上の別directoryへ明示する。APIのrepresentation bytesがpin済みhashと変わっていればexit 2になり、新packageは公開されない。`/mnt/c`はatomic no-replace directory公開を保証できないためv0.1では`UNSUPPORTED`になる。

```bash
python3 -m rulekernel source-fetch-egov \
  examples/sources/penal-code-41/source-spec.json \
  --bundle /tmp/penal-code-41-new
```

このsnapshotは条文の保存・構造抽出まで。T05で解釈IRとCoreを結ぶ一般経路は作ったが、刑法41条の手書き解釈と年齢条件の検査はT07で行う。
