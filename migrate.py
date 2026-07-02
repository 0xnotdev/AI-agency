import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")

def run_migration():
    if not DATABASE_URL:
        print("DATABASE_URL is not set.")
        return
        
    print("Connecting to Supabase...")
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cursor = conn.cursor()
    
    with open("migrations/004_multitenant_routing.sql", "r") as f:
        sql = f.read()
    
    print("Executing migration script...")
    cursor.execute(sql)
    print("Migration successful.")
    
    cursor.close()
    conn.close()

if __name__ == "__main__":
    run_migration()
