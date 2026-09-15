# 星見クラブ資料形式の固定原文

T03.1でscope期待と段階別到達可能性を接続した架空規約2条。実在の法令・団体規約ではない。原文は [club20/fixed.json](../../club20/fixed.json) の第19条・第20条の `source` と同一である。[手書き解釈と保存証拠](../../interpretations/handbook-scope/README.md)がこのpackageを使う。

1. 第19条　学生ではない参加者に配布する資料の形式は、紙版とする。
2. 第20条　26歳以上の参加者に配布する資料の形式は、第19条にかかわらず電子版とする。

第20条中の「第19条」は、第19条のsource unitへ `resolved` として保存した。bundleはlocal importであり、公式取得や第三者timestampを表さない。

- [source.xml](source.xml): UTF-8原文2単位。
- [source-spec.json](source-spec.json): raw hash、抽出profile、完全path、期待本文、resolved reference。
- [bundle/](bundle/): 独立checker通過後のpackage。

| 項目 | SHA-256 |
|---|---|
| raw source | `434f4f1b4ec82cb1a75d91aced7d2cc143ff90ef533063ce6eb33152d3034166` |
| capture spec | `7c4dbcefee2f0baf6bfe0b4d4360b3f59e9d2fdf1fe7cc0d4f1c3971d19d0c76` |
| extracted text | `e33a8fe5b6eef1c1b9db84a39cefb29810fc45a68ee1419765719f7e8c5a99f4` |
| source-unit manifest | `1170350e93942928d90c68101169a7560b0f280997018e542963cbc614081c11` |
| bundle lock | `52ca5a149fe1e901b62854ac4b12c613e0ab8261e54a4b6a932f2963bd0dc8e4` |

取得記録値は `2026-09-15T13:38:20Z`。

~~~bash
python3 -m rulekernel verify-source examples/sources/handbook-scope/source-spec.json examples/sources/handbook-scope/bundle --expected-bundle-sha256 52ca5a149fe1e901b62854ac4b12c613e0ab8261e54a4b6a932f2963bd0dc8e4
~~~

この検査はbytes・抽出・manifest・取得記録の整合を確認する。2条の意味、`expected_inactive`の妥当性、法的な正しさは証明しない。
