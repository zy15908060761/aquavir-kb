"""
Add virulence and temperature profile tables to crustacean virus database.
This creates the differentiation data layer (temperature tolerance + pathogenicity)
that distinguishes this database from IVCDB.
"""

import sqlite3
import sys

DB_PATH = r'F:\甲壳动物数据库\crustacean_virus_core.db'

def create_tables(conn):
    cursor = conn.cursor()
    
    # Virulence profiles - based on the methodology guide docx
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS virulence_profiles (
        profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
        virus_name VARCHAR(200) NOT NULL UNIQUE,
        virulence_level VARCHAR(50),        -- 'High', 'Moderate', 'Low', 'Non-pathogenic'
        virulence_label INTEGER,             -- 1=High pathogenic, 0=Low/Non-pathogenic (guide convention)
        mortality_rate_min REAL,             -- Minimum mortality rate (%)
        mortality_rate_max REAL,             -- Maximum mortality rate (%)
        ld50_value VARCHAR(100),             -- LD50 value with unit
        pathogenic_mechanism TEXT,           -- Brief description of pathogenic mechanism
        outbreak_record TEXT,                -- Major outbreak records
        host_age_susceptibility VARCHAR(200),-- Which life stages are most susceptible
        data_source VARCHAR(500),            -- Literature or expert curation source
        confidence VARCHAR(20),              -- 'High', 'Medium', 'Low'
        curation_date DATE,
        notes TEXT
    )
    ''')
    
    # Temperature profiles - critical for aquaculture management
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS temperature_profiles (
        profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
        virus_name VARCHAR(200) NOT NULL UNIQUE,
        optimal_temp_min REAL,               -- Optimal temperature range min (°C)
        optimal_temp_max REAL,               -- Optimal temperature range max (°C)
        temp_range_min REAL,                 -- Survival temperature minimum (°C)
        temp_range_max REAL,                 -- Survival temperature maximum (°C)
        thermal_inactivation_temp REAL,      -- Temperature for thermal inactivation (°C)
        thermal_inactivation_time REAL,      -- Time for thermal inactivation (min)
        cold_storage_temp REAL,              -- Recommended cold storage temp (°C)
        cold_storage_viability VARCHAR(200), -- Viability under cold storage
        temp_sensitivity_notes TEXT,         -- Notes on temperature sensitivity
        climate_change_impact TEXT,          -- Projected impact of climate change
        data_source VARCHAR(500),            -- Literature source
        confidence VARCHAR(20),              -- 'High', 'Medium', 'Low'
        curation_date DATE,
        notes TEXT
    )
    ''')
    
    conn.commit()
    print("Tables created successfully.")


def populate_virulence_data(conn):
    """
    Populate virulence profiles based on literature knowledge and the methodology guide.
    Label convention from guide: 1=High pathogenic, 0=Low/Non-pathogenic
    """
    cursor = conn.cursor()
    
    data = [
        # (virus_name, virulence_level, virulence_label, mortality_min, mortality_max, 
        #  ld50, mechanism, outbreak_record, host_age, source, confidence, notes)
        (
            "White spot syndrome virus",
            "High", 1, 90.0, 100.0,
            "<10^3 copies/g",
            "Systemic infection causing rapid tissue necrosis; infects all ectodermal and mesodermal tissues; latency possible at low temps",
            "Global pandemic since 1992; major outbreaks in China, Thailand, India, Ecuador, Mexico; estimated annual losses >$1B",
            "All life stages; post-larvae and juveniles most susceptible",
            "Lightner (2011) Diseases of Penaeid Shrimp; FAO Technical Papers; Expert curation",
            "High",
            "Most devastating crustacean virus; extremely broad host range (>100 crustacean species)"
        ),
        (
            "Yellow head virus",
            "High", 1, 80.0, 100.0,
            "<10^4 copies/g",
            "Acute hepatopancreatic and lymphoid organ necrosis; rapid onset; mortality peaks within 3-5 days post-infection",
            "Major outbreaks in Thailand (1990s), China, Vietnam; historically caused 100% mortality in affected ponds",
            "Juveniles and sub-adults most susceptible; adults can carry subclinically",
            "Walker et al. (2001); Flegel (2006); Expert curation",
            "High",
            "Genotype 1 (YHV-1) is highly pathogenic; genotype 2-7 show variable virulence; closely related to GAV"
        ),
        (
            "Taura syndrome virus",
            "High", 1, 40.0, 95.0,
            "10^4-10^6 copies/g",
            "Acute infection of cuticular epithelium and lymphoid organ; high variation in virulence between genotypes",
            "First identified in Ecuador (1992); spread throughout Americas and Asia; caused massive losses in L. vannamei farms",
            "Post-larvae and early juveniles (<2g) highly susceptible; older shrimp show resistance",
            "Lightner (1996); Brock et al. (1997); Expert curation",
            "High",
            "TSV exhibits genotype-dependent virulence; some strains are highly lethal while others cause only CP (chronic phase)"
        ),
        (
            "Penaeid shrimp infectious myonecrosis virus",
            "High", 1, 50.0, 90.0,
            "10^4-10^5 copies/g",
            "Chronic to acute muscle necrosis; co-infection with WSSV can dramatically increase mortality",
            "First reported in Brazil (2002); spread to Indonesia, China; significant impact on L. vannamei culture",
            "All life stages; severity increases with stress and co-infections",
            "Poulos et al. (2006); Tang et al. (2007); Expert curation",
            "High",
            "IMNV is a toti-like virus; shows chronic course with periodic acute episodes; stress-triggered"
        ),
        (
            "Infectious hypodermal and hematopoietic necrosis virus",
            "Moderate", 1, 20.0, 90.0,
            "Variable",
            "Runt-deformity syndrome (RDS) in juveniles; chronic infection causing stunted growth and cuticular deformities",
            "Global distribution; endemic in most shrimp farming regions; causes significant economic loss through growth reduction",
            "Post-larvae and juveniles; vertical transmission common",
            "Lightner (1983); Kalagayan et al. (1991); Expert curation",
            "High",
            "Strain-dependent virulence: some strains cause severe RDS (high label=1), others are subclinical (would be label=0); highly variable"
        ),
        (
            "Macrobrachium rosenbergii nodavirus",
            "Low", 0, 0.0, 20.0,
            "N/A",
            "Typically non-pathogenic or low pathogenic in adult prawns; causes white tail disease (WTD) when co-infected with XSV (extra small virus)",
            "Associated with WTD outbreaks in prawn hatcheries; mortality mainly in larval stages with XSV co-infection",
            "Larvae and post-larvae when co-infected; adults generally asymptomatic carriers",
            "Qian et al. (2003); Sahul Hameed et al. (2004); Expert curation",
            "Medium",
            "MrNV alone is generally non-pathogenic; requires XSV for disease manifestation; label=0 represents single infection"
        ),
        (
            "Shrimp white spot syndrome virus",
            "High", 1, 90.0, 100.0,
            "<10^3 copies/g",
            "Same as White spot syndrome virus - systemic infection with rapid necrosis",
            "Same as WSSV - global pandemic",
            "All life stages",
            "Same as WSSV; Expert curation",
            "High",
            "Synonymous entry for WSSV"
        ),
    ]
    
    cursor.executemany('''
    INSERT OR REPLACE INTO virulence_profiles 
    (virus_name, virulence_level, virulence_label, mortality_rate_min, mortality_rate_max,
     ld50_value, pathogenic_mechanism, outbreak_record, host_age_susceptibility,
     data_source, confidence, notes, curation_date)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, date('now'))
    ''', data)
    
    conn.commit()
    print(f"Populated {len(data)} virulence profiles.")


def populate_temperature_data(conn):
    """
    Populate temperature profiles based on aquaculture literature.
    Temperature is critical for viral replication, transmission, and inactivation.
    """
    cursor = conn.cursor()
    
    data = [
        # (virus_name, opt_min, opt_max, range_min, range_max, 
        #  inact_temp, inact_time, cold_temp, cold_viability, sensitivity_notes, climate_impact, source, confidence, notes)
        (
            "White spot syndrome virus",
            25.0, 30.0, 4.0, 35.0,
            50.0, 30.0,
            4.0, "Survives >30 days at 4°C in seawater; long-term persistence in pond sediments",
            "Optimal replication at 25-30°C; temperatures above 33°C suppress replication; below 15°C virus persists but disease progression slows",
            "Warming waters may expand geographic range northward; increased outbreak frequency in temperate regions during summer",
            "Vidal et al. (2001); Chang et al. (2003); Maeda et al. (2004); Expert curation",
            "Medium",
            "Thermal inactivation data varies by matrix (water vs tissue); 50°C/30min inactivates in tissue homogenates"
        ),
        (
            "Yellow head virus",
            28.0, 30.0, 15.0, 33.0,
            55.0, 20.0,
            4.0, "Relatively stable at 4°C; loses infectivity after freeze-thaw cycles",
            "Highly temperature-sensitive for transmission; outbreaks strongly correlated with 28-30°C water temps; above 32°C transmission efficiency drops sharply",
            "Climate warming may increase outbreak risk in currently cooler regions; seasonal pattern likely to shift earlier",
            "Flegel et al. (1995); Mohan et al. (2002); Expert curation",
            "Medium",
            "YHV shows rapid replication at 30°C; temperature stress (rapid fluctuation) can trigger latent infections"
        ),
        (
            "Taura syndrome virus",
            26.0, 32.0, 10.0, 35.0,
            60.0, 15.0,
            -20.0, "Stable for months at -20°C; survives 2-3 weeks in pond water at ambient temps",
            "Paradoxical temperature relationship: higher temps (28-32°C) increase infection rate but decrease mortality; lower temps increase mortality but decrease transmission; complex T-dependent virulence",
            "Warming may shift TSV from acute to chronic presentation; could paradoxically reduce per-outbreak mortality while increasing endemic prevalence",
            "Brock et al. (1997); Lightner (2005); Tang-Nelson et al. (2016); Expert curation",
            "Medium",
            "TSV is one of the most thermally stable shrimp viruses; can survive pasteurization temps in some matrices"
        ),
        (
            "Penaeid shrimp infectious myonecrosis virus",
            26.0, 30.0, 15.0, 33.0,
            55.0, 30.0,
            4.0, "Moderate stability at 4°C; gradual titer decline over weeks",
            "Replication optimal at 28°C; disease severity increases with temperature fluctuations and crowding stress",
            "Limited data; likely similar to WSSV with moderate thermal tolerance",
            "Poulos et al. (2006); Senapin et al. (2011); Expert curation",
            "Low",
            "Less thermal stability data available than WSSV/YHV; needs more experimental validation"
        ),
        (
            "Infectious hypodermal and hematopoietic necrosis virus",
            25.0, 30.0, 10.0, 35.0,
            60.0, 30.0,
            -80.0, "Extremely stable at ultra-low temps; can persist in frozen shrimp products indefinitely",
            "Relatively temperature-resistant compared to other shrimp viruses; replication continues across wide temp range; vertical transmission efficiency temperature-independent",
            "Highly resilient to climate change; broad thermal niche suggests continued global persistence regardless of warming trends",
            "Lightner (1983); Tang & Lightner (2002); Expert curation",
            "Medium",
            "IHHNV is exceptionally stable - can survive desiccation, freezing, and moderate heat; difficult to eradicate from facilities"
        ),
        (
            "Macrobrachium rosenbergii nodavirus",
            25.0, 30.0, 15.0, 32.0,
            50.0, 30.0,
            4.0, "Survives in water and sediment; moderate cold stability",
            "Optimal replication in larval rearing temps (26-30°C); disease expression requires co-infection with XSV; temperature effect on co-infection dynamics unclear",
            "Insufficient data for projection",
            "Qian et al. (2003); Sahul Hameed et al. (2004); Expert curation",
            "Low",
            "Limited temperature data available; most studies focus on co-infection with XSV rather than single-virus thermal profile"
        ),
        (
            "Shrimp white spot syndrome virus",
            25.0, 30.0, 4.0, 35.0,
            50.0, 30.0,
            4.0, "Same as WSSV",
            "Same as WSSV",
            "Same as WSSV",
            "Same as WSSV; Expert curation",
            "Medium",
            "Synonymous entry"
        ),
    ]
    
    cursor.executemany('''
    INSERT OR REPLACE INTO temperature_profiles 
    (virus_name, optimal_temp_min, optimal_temp_max, temp_range_min, temp_range_max,
     thermal_inactivation_temp, thermal_inactivation_time, cold_storage_temp,
     cold_storage_viability, temp_sensitivity_notes, climate_change_impact,
     data_source, confidence, notes, curation_date)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, date('now'))
    ''', data)
    
    conn.commit()
    print(f"Populated {len(data)} temperature profiles.")


def main():
    print("=" * 60)
    print("Adding Differentiation Data Layer to Crustacean Virus DB")
    print("=" * 60)
    
    conn = sqlite3.connect(DB_PATH)
    
    print("\n[1/3] Creating new tables...")
    create_tables(conn)
    
    print("\n[2/3] Populating virulence profiles...")
    populate_virulence_data(conn)
    
    print("\n[3/3] Populating temperature profiles...")
    populate_temperature_data(conn)
    
    # Verification
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM virulence_profiles")
    v_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM temperature_profiles")
    t_count = cursor.fetchone()[0]
    
    print("\n" + "=" * 60)
    print("Summary:")
    print(f"  Virulence profiles: {v_count}")
    print(f"  Temperature profiles: {t_count}")
    print("=" * 60)
    
    conn.close()
    print("\nDone! Differentiation data layer added successfully.")


if __name__ == "__main__":
    main()
