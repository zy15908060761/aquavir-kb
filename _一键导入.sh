#!/bin/bash
# 在 PowerShell 中执行以下命令（逐行复制粘贴）

cd F:\甲壳动物数据库

# 1. 导入7,160篇文献到 ref_literatures
sqlite3 crustacean_virus_core.db ".mode tabs" ".import import_ready/01_ref_literatures.tsv ref_literatures"

# 2. 验证导入数量
sqlite3 crustacean_virus_core.db "SELECT COUNT(*) FROM ref_literatures;"
