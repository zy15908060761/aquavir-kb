"""
根据国家名称回填大致中心经纬度，用于地图散点展示
"""

import sqlite3

DB_PATH = r'F:\甲壳动物数据库\crustacean_virus_core.db'

# Country name -> [longitude, latitude] (approximate centroids)
COUNTRY_CENTROIDS = {
    'China': [104.0, 35.0],
    'Thailand': [100.5, 13.7],
    'Japan': [138.0, 36.0],
    'Australia': [133.8, -25.3],
    'Malaysia': [101.7, 3.2],
    'Brazil': [-51.9, -14.2],
    'Vietnam': [108.3, 14.1],
    'India': [78.9, 20.6],
    'Peru': [-75.0, -9.2],
    'Mexico': [-102.5, 23.6],
    'Indonesia': [113.9, -0.8],
    'United States': [-95.7, 37.1],
    'South Korea': [127.8, 36.5],
    'Iran': [53.7, 32.4],
    'Taiwan': [120.9, 23.7],
    'Hong Kong': [114.2, 22.3],
    'Ecuador': [-78.2, -1.8],
    'Colombia': [-74.3, 4.6],
    'Belize': [-88.5, 17.2],
    'France': [2.2, 46.2],
    'United Kingdom': [-3.4, 55.4],
    'Germany': [10.4, 51.2],
    'Israel': [34.9, 31.0],
    'Madagascar': [46.9, -18.8],
    'Tanzania': [34.9, -6.4],
    'Mozambique': [35.5, -18.7],
    'Kenya': [37.9, 0.2],
    'Bangladesh': [90.4, 23.7],
    'Sri Lanka': [80.8, 7.9],
    'Panama': [-80.8, 8.5],
}


def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    updated = 0
    for country, (lon, lat) in COUNTRY_CENTROIDS.items():
        c.execute("""
            UPDATE sample_collections 
            SET longitude = ?, latitude = ?
            WHERE country = ? AND (longitude IS NULL OR latitude IS NULL)
        """, (lon, lat, country))
        if c.rowcount > 0:
            updated += c.rowcount
            print(f'  {country}: {c.rowcount} records updated')
    
    conn.commit()
    
    c.execute('SELECT COUNT(*) FROM sample_collections WHERE latitude IS NOT NULL AND longitude IS NOT NULL')
    total_with_geo = c.fetchone()[0]
    
    print(f'\nTotal records with lat/lon now: {total_with_geo}')
    conn.close()


if __name__ == '__main__':
    main()
