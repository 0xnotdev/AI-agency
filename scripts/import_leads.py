import os
import sys
import csv
import argparse

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase import create_client, Client
from app.core.config import settings

def import_leads(client_id: str, csv_path: str):
    supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    
    # Verify client exists
    client_res = supabase.table("clients").select("id").eq("id", client_id).execute()
    if not client_res.data:
        print(f"Error: Client ID {client_id} not found.")
        sys.exit(1)
        
    print(f"Importing leads for client {client_id} from {csv_path}...")
    
    success_count = 0
    error_count = 0
    
    with open(csv_path, mode='r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        
        # Normalize headers
        headers = [h.strip().lower() for h in reader.fieldnames] if reader.fieldnames else []
        reader.fieldnames = headers
        
        for row_num, row in enumerate(reader, start=1):
            name = row.get("name", "").strip()
            phone = row.get("phone", "").strip()
            email = row.get("email", "").strip()
            external_id = row.get("external_lead_id", "").strip() or None
            
            if not name:
                print(f"Row {row_num}: Missing name. Skipping.")
                error_count += 1
                continue
                
            if not phone and not email:
                print(f"Row {row_num}: Missing both phone and email. Skipping.")
                error_count += 1
                continue
                
            lead_data = {
                "client_id": client_id,
                "name": name,
                "phone": phone if phone else None,
                "email": email if email else None,
                "source": "reactivation",
                "status": "new"
            }
            
            if external_id:
                lead_data["external_lead_id"] = external_id
                
            try:
                # Use upsert to handle duplicates cleanly if external_lead_id is provided
                # In Supabase REST, upsert works on primary key or unique constraints.
                if external_id:
                    supabase.table("leads").upsert(lead_data, on_conflict="client_id,external_lead_id").execute()
                else:
                    supabase.table("leads").insert(lead_data).execute()
                success_count += 1
            except Exception as e:
                print(f"Row {row_num}: Error importing lead: {str(e)}")
                error_count += 1
                
    print(f"\nImport Complete: {success_count} successful, {error_count} failed.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import dormant leads from CSV for reactivation.")
    parser.add_argument("--client-id", required=True, help="Supabase UUID for the client")
    parser.add_argument("--csv", required=True, help="Path to the CSV file")
    
    args = parser.parse_args()
    import_leads(args.client_id, args.csv)
