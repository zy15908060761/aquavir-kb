"""
将 sample_collections 中的国家中心坐标升级为省份/州级中心坐标。
仅覆盖数据库中实际存在省份数据的地区。
"""

import sqlite3

DB_PATH = r'F:\甲壳动物数据库\crustacean_virus_core.db'

# 省份/州名 → (longitude, latitude)
# 覆盖 sample_collections.province 中所有有意义的省份名
PROVINCE_CENTROIDS = {
    # === 中国 ===
    '甘肃省': (104.0, 36.0),
    'Zhejiang': (120.2, 30.3),
    'ZheJiang province': (120.2, 30.3),
    'ZheJiang': (120.2, 30.3),
    'Zhanjiang': (110.4, 21.2),
    'Ningbo': (121.5, 29.9),
    'Jiangsu': (119.8, 33.0),
    'Hebei': (114.5, 38.0),
    'Hainan': (109.5, 19.2),
    'GuangXi': (108.3, 23.8),
    'Guangxi': (108.3, 23.8),
    'Guangdong': (113.3, 23.1),
    'Fujian': (117.9, 26.1),
    'Shandong': (117.0, 36.3),
    'Liaoning': (122.0, 41.1),
    'Jiangxi': (115.9, 27.6),
    'Anhui': (117.2, 31.8),
    'Henan': (113.7, 33.9),
    'Hubei': (112.2, 30.6),
    'Hunan': (112.0, 27.4),
    'Sichuan': (103.0, 30.5),
    'Yunnan': (101.9, 24.8),
    'Guizhou': (106.7, 26.8),
    'Shaanxi': (109.5, 35.6),
    'Shanxi': (112.5, 37.6),
    'Jilin': (126.5, 43.7),
    'Heilongjiang': (127.5, 47.9),
    'Qinghai': (96.0, 35.5),
    'Beijing': (116.4, 39.9),
    'Tianjin': (117.2, 39.1),
    'Shanghai': (121.5, 31.2),
    'Chongqing': (106.5, 29.5),
    'Xinjiang': (85.0, 41.0),
    'Nei Mongol': (111.7, 40.8),
    'Inner Mongolia': (111.7, 40.8),
    'Xizang': (88.0, 31.7),
    'Tibet': (88.0, 31.7),
    'Ningxia': (106.3, 37.3),
    'Hong Kong': (114.2, 22.3),
    'Macau': (113.5, 22.2),
    'Taiwan': (120.9, 23.7),

    # === 墨西哥 ===
    'Zacatecas': (-102.6, 23.0),
    'Sonora': (-110.3, 29.3),
    'Sinaloa': (-107.4, 25.0),
    'Sinaloa and Nayarit': (-106.5, 23.0),
    'Northern coast of Sinaloa': (-108.0, 25.8),
    'Northern Coast of Sinaloa': (-108.0, 25.8),
    'Guasave': (-108.5, 25.6),
    'southern Sonora': (-109.6, 27.5),
    'Tamaulipas': (-98.2, 24.0),
    'Nayarit': (-105.1, 22.0),
    'Northwest': (-107.0, 28.0),
    'Gulf of California': (-111.0, 28.0),

    # === 印度 ===
    'Maharashtra': (75.7, 19.7),
    'Tamil Nadu': (78.7, 10.8),
    'Andhra Pradesh': (79.7, 15.9),
    'West Bengal': (87.9, 24.0),
    'Chennai': (80.3, 13.1),
    'Saphale': (72.8, 19.6),
    'Parangipettai': (79.8, 11.5),
    'West coast': (73.0, 17.0),
    'east coast': (82.0, 16.0),
    'East coast': (82.0, 16.0),
    'shrimp pond on the west coast': (73.0, 17.0),

    # === 菲律宾 ===
    'Camarines Norte': (122.7, 14.1),
    'Zamboanga del Sur': (123.2, 7.9),
    'Occidental Mindoro': (120.9, 13.0),
    'Leyte': (124.8, 10.9),
    'Batangas': (121.0, 13.8),

    # === 孟加拉国 ===
    'ঢাকা বিভাগ': (90.4, 23.8),
    'Satkhira Sadar': (89.1, 22.7),
    'Satkhira': (89.1, 22.7),
    'Assasuni': (89.2, 22.5),
    'Shymnagar': (89.3, 22.3),
    'Kaliganj': (89.0, 22.5),
    'Debhata': (89.1, 22.7),
    'Deabhata': (89.1, 22.7),
    'Burigoalini': (89.2, 22.2),

    # === 伊朗 ===
    'استان یزد': (55.0, 32.0),
    'Chabahar': (60.6, 25.3),
    'Khouzestan': (49.0, 31.0),
    'Choebdeh': (48.7, 30.2),

    # === 越南 ===
    'Tỉnh Gia Lai': (108.0, 13.8),
    'Binh Dinh': (109.0, 14.1),
    'Ho Chi MInh': (106.7, 10.8),
    'Bac lieu': (105.7, 9.3),
    'southern': (105.8, 10.0),

    # === 印度尼西亚 ===
    'Kalimantan Tengah': (113.5, -1.7),
    'Yogyakarta': (110.4, -7.8),
    'Surabaya': (112.7, -7.3),

    # === 日本 ===
    '長野県': (138.0, 36.2),
    'Okinawa': (127.8, 26.3),
    'Miyazaki': (131.3, 32.0),
    'Yamaguchi': (131.5, 34.2),
    'Shizuoka': (138.2, 34.9),
    'Fukuoka': (130.4, 33.5),
    'Chiba': (140.1, 35.6),
    'Aichi': (137.2, 35.1),

    # === 韩国 ===
    '충청북도': (127.5, 36.8),
    'west coast': (126.0, 36.0),

    # === 泰国 ===
    'Songkla': (100.6, 7.2),
    'Chanthaburi': (102.1, 12.6),
    'Chachoengsao': (101.2, 13.7),
    'Samut Sakorn': (100.3, 13.5),
    'Ratchaburi': (99.8, 13.5),
    'Nakornpratom': (100.0, 13.8),
    'Nakornphatom': (100.0, 13.8),
    'Chonburi': (100.9, 13.2),
    'Cholburi': (100.9, 13.2),
    'Chatcheonchao': (101.2, 13.7),
    'Chantaburi': (102.1, 12.6),
    'Eastern hemisphere': (101.0, 13.5),

    # === 美国 ===
    'Kansas': (-98.3, 39.0),
    'Texas': (-99.5, 31.4),
    'Hawaii': (-157.5, 20.8),
    'South Carolina': (-80.9, 33.7),
    'Louisiana': (-91.9, 30.4),
    'National Zoo': (-77.0, 38.9),
    'Chehalis River': (-123.5, 46.8),

    # === 巴西 ===
    'Mato Grosso': (-56.0, -12.5),
    'Rio Grande do Norte': (-36.5, -5.5),
    'State of Ceara': (-39.0, -4.5),

    # === 澳大利亚 ===
    'northern Queensland': (144.0, -17.0),
    'Murray River Wemen': (142.0, -34.5),
    'Murray River Nursery Bend': (141.5, -34.5),
    'Macquarie River': (147.5, -33.0),
    'Edward River': (144.0, -35.0),
    'Barwon River': (148.0, -30.0),
    'Gulf of Carpentaria near Weipa': (141.5, -12.5),
    'East Coast prawn farm': (153.0, -27.5),

    # === 其他 ===
    # Argentina
    'La Pampa': (-65.0, -37.0),
    # Belize
    'Belize District': (-88.4, 17.5),
    # Colombia
    'Cundinamarca': (-73.9, 4.6),
    # Costa Rica
    'San José': (-84.1, 9.9),
    # Ecuador
    'Morona Santiago': (-78.0, -2.5),
    # Egypt
    'الوادي الجديد': (29.0, 24.5),
    # Honduras
    'Olancho': (-86.0, 14.8),
    # Kazakhstan
    'Ұлытау облысы': (67.0, 48.0),
    # Libya
    'شعبية الجفرة': (17.0, 28.0),
    # Madagascar
    'Itasy': (46.7, -19.0),
    # Malaysia
    'Kuala Lumpur': (101.7, 3.1),
    # Mozambique
    'Sofala': (34.6, -19.5),
    # Nicaragua
    'Matagalpa': (-85.9, 12.9),
    # Peru
    'Huánuco': (-76.2, -9.9),
    # Russia
    'Красноярский край': (93.0, 63.0),
    # Saudi Arabia
    'منطقة الرياض': (45.0, 24.0),
    # South Africa
    'Northern Cape': (22.0, -29.0),
    # Sri Lanka
    'Puttalam': (79.8, 8.0),
    'Chilaw': (79.8, 7.6),
    'Batticaloa': (81.7, 7.7),
    # Venezuela
    'Bolívar': (-63.5, 7.0),
    # Algeria
    'أدرار ⴰⴷⵔⴰⵔ': (0.2, 27.9),
    # Tunisia
    'ولايت قابس': (10.0, 33.8),
    # Eritrea
    'Massawa': (39.5, 15.6),
    # Italy
    'Lazio': (12.7, 41.8),
    # New Zealand
    'Wellington': (174.8, -41.3),
    # Norway
    'Arctic Ocean': (10.0, 80.0),
    # Myanmar
    'စစ်ကိုင်းတိုင်းဒေသကြီး': (95.5, 23.5),
    # Germany (ignore non-geographic)
    'aquarium trade': None,
    # Taiwan
    'southern region': (120.5, 23.0),
    'south coastal waters': (120.5, 22.5),
}


def _normalize_country_name(raw):
    """Handle common country name variants."""
    mapping = {
        'USA': 'United States',
        'Korea': 'South Korea',
        'Korea, South': 'South Korea',
        'United States of America': 'United States',
    }
    return mapping.get(raw, raw)


def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Add coordinate_precision column if not exists
    try:
        c.execute("ALTER TABLE sample_collections ADD COLUMN coordinate_precision TEXT DEFAULT 'country'")
        print('Added coordinate_precision column')
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Mark existing NULLs as 'country' precision
    c.execute("UPDATE sample_collections SET coordinate_precision = 'country' WHERE coordinate_precision IS NULL")
    print(f'Initialized {c.rowcount} records as country precision')

    # Set NULL-coordinate records to 'none'
    c.execute("UPDATE sample_collections SET coordinate_precision = 'none' WHERE latitude IS NULL")
    none_count = c.rowcount
    print(f'Marked {none_count} records as "none" (no coordinates)')

    # Now upgrade province centroids
    upgraded = 0
    skipped = 0
    detail = []

    for prov_name, coords in PROVINCE_CENTROIDS.items():
        if coords is None:
            skipped += c.execute(
                "SELECT COUNT(*) FROM sample_collections WHERE province = ?",
                (prov_name,)
            ).fetchone()[0]
            continue

        lon, lat = coords
        c.execute("""
            UPDATE sample_collections
            SET longitude = ?, latitude = ?, coordinate_precision = 'province'
            WHERE province = ?
        """, (lon, lat, prov_name))

        if c.rowcount > 0:
            upgraded += c.rowcount
            detail.append(f'  {prov_name}: {c.rowcount} records -> ({lat}, {lon})')

    conn.commit()

    # Identify precise coordinates:
    # 1) Countries NOT in centroid list = inherently real coordinates
    # 2) Countries IN centroid list but coordinates DON'T match = real coordinates
    country_centroids = {
        'China': (104.0, 35.0), 'Thailand': (100.5, 13.7), 'Japan': (138.0, 36.0),
        'Australia': (133.8, -25.3), 'Malaysia': (101.7, 3.2), 'Brazil': (-51.9, -14.2),
        'Vietnam': (108.3, 14.1), 'India': (78.9, 20.6), 'Mexico': (-102.5, 23.6),
        'Indonesia': (113.9, -0.8), 'United States': (-95.7, 37.1),
        'South Korea': (127.8, 36.5), 'Iran': (53.7, 32.4), 'Taiwan': (120.9, 23.7),
        'Ecuador': (-78.2, -1.8), 'Colombia': (-74.3, 4.6), 'Belize': (-88.5, 17.2),
        'France': (2.2, 46.2), 'United Kingdom': (-3.4, 55.4), 'Germany': (10.4, 51.2),
        'Israel': (34.9, 31.0), 'Madagascar': (46.9, -18.8), 'Tanzania': (34.9, -6.4),
        'Mozambique': (35.5, -18.7), 'Kenya': (37.9, 0.2), 'Bangladesh': (90.4, 23.7),
        'Sri Lanka': (80.8, 7.9), 'Panama': (-80.8, 8.5), 'Hong Kong': (114.2, 22.3),
        'Peru': (-75.0, -9.2),
    }

    centroid_countries = list(country_centroids.keys())
    placeholders = ','.join(['?'] * len(centroid_countries))

    # Countries NOT in the centroid list = inherently real coordinates
    c.execute(f"""
        UPDATE sample_collections
        SET coordinate_precision = 'precise'
        WHERE coordinate_precision = 'country'
          AND latitude IS NOT NULL
          AND country NOT IN ({placeholders})
    """, centroid_countries)
    precise_non_centroid = c.rowcount

    # Countries IN centroid list but coordinates DON'T match = also real
    precise_mismatch = 0
    for country, (c_lon, c_lat) in country_centroids.items():
        c.execute("""
            UPDATE sample_collections
            SET coordinate_precision = 'precise'
            WHERE country = ?
              AND coordinate_precision = 'country'
              AND latitude IS NOT NULL
              AND (ABS(latitude - ?) > 0.1 OR ABS(longitude - ?) > 0.1)
        """, (country, c_lat, c_lon))
        precise_mismatch += c.rowcount

    conn.commit()
    print(f'Marked {precise_non_centroid} records as precise (non-centroid country)')
    print(f'Marked {precise_mismatch} records as precise (non-matching coords)')

    # Count precision levels
    c.execute("SELECT coordinate_precision, COUNT(*) FROM sample_collections GROUP BY coordinate_precision")
    precision_counts = {r[0]: r[1] for r in c.fetchall()}

    print(f'\nUpgraded {upgraded} records from country to province level')
    print(f'Skipped {skipped} records (non-geographic province values)')
    print(f'\nCoordinate precision breakdown:')
    for level, count in sorted(precision_counts.items()):
        print(f'  {level}: {count}')

    # Show province upgrade details (top 10) - write to file to avoid encoding issues
    detail.sort(key=lambda x: -int(x.split(':')[1].split()[0]))
    with open('province_upgrade_log.txt', 'w', encoding='utf-8') as f:
        f.write('Province coordinate upgrades:\n')
        for d in detail:
            f.write(d + '\n')
    print(f'\nProvince upgrade details written to province_upgrade_log.txt ({len(detail)} provinces)')

    conn.close()


if __name__ == '__main__':
    main()
