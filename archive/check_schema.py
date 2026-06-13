#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sqlite3
conn = sqlite3.connect(r'F:\甲壳动物数据库\crustacean_virus_core.db')
c = conn.cursor()
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
for t in c.fetchall():
    tname = t[0]
    print(f'=== {tname} ===')
    c.execute(f'PRAGMA table_info({tname})')
    cols = [col[1] for col in c.fetchall()]
    print(cols)
    c.execute(f'SELECT COUNT(*) FROM {tname}')
    cnt = c.fetchone()[0]
    print(f'COUNT: {cnt}')
    print()
conn.close()
