"""Generate realistic synthetic Indian addresses and visits for demo."""

import json
import math
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import numpy as np

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.database import init_db, db_session
from data.repositories import AccountRepository, VisitRepository
from app.schemas import Account, Visit, VisitOutcome, TrajectoryPoint


# Configuration
SEED = 42
random.seed(SEED)
np.random.seed(SEED)

# Base location: Bangalore
BASE_LAT = 12.9716
BASE_LON = 77.5946

# Indian cities with approximate coordinates
CITIES = {
    "Bangalore": (12.9716, 77.5946),
    "Mumbai": (19.0760, 72.8777),
    "Delhi": (28.7041, 77.1025),
    "Chennai": (13.0827, 80.2707),
    "Hyderabad": (17.3850, 78.4867),
    "Pune": (18.5204, 73.8567),
    "Kolkata": (22.5726, 88.3639),
    "Ahmedabad": (23.0225, 72.5714),
}

# Common Indian localities
LOCALITIES = [
    "MG Road", "Indiranagar", "Koramangala", "HSR Layout", "Whitefield",
    "Jayanagar", "Malleshwaram", "Rajajinagar", "Banashankari", "JP Nagar",
    "Andheri", "Bandra", "Powai", "Malad", "Goregaon",
    "Connaught Place", "Karol Bagh", "Lajpat Nagar", "Saket", "Dwarka",
    "T Nagar", "Anna Nagar", "Adyar", "Velachery", "OMR",
    "Banjara Hills", "Jubilee Hills", "Madhapur", "Gachibowli", "Kukatpally",
    "Kothrud", "Hinjewadi", "Viman Nagar", "Kharadi", "Hadapsar",
    "Salt Lake", "Dum Dum", "Ballygunge", "Behala", "Gariahat",
    "Maninagar", "Vastrapur", "Satellite", "Bopal", "Thaltej",
]

# Common landmarks
LANDMARKS = [
    "Hanuman Temple", "SBI Bank", "Ration Shop", "Petrol Pump",
    "Bus Stop", "Metro Station", "Hospital", "School", "College",
    "Post Office", "Police Station", "Market", "Shopping Mall",
    "Park", "Mosque", "Church", "Gurudwara", "Dargah",
    "Water Tank", "Electricity Substation", "Telephone Exchange",
    "Community Hall", "Library", "Playground", "Cricket Ground",
]

# Common Indian names for agents
AGENT_NAMES = [
    "Ramesh Kumar", "Suresh Singh", "Priya Sharma", "Amit Patel",
    "Sunita Devi", "Rajesh Gupta", "Anita Verma", "Vikram Joshi",
    "Deepak Yadav", "Pooja Mehta", "Sanjay Rao", "Kavita Nair",
]

# Address templates
CLEAN_TEMPLATES = [
    "Flat {num}, {building}, {locality}, {city}",
    "{num}, {street}, {locality}, {city} - {pincode}",
    "House {num}, {building} Society, {locality}, {city}",
    "Plot {num}, {sector}, {city} - {pincode}",
    "{building} Apartment, Flat {num}, {locality}, {city}",
]

MESSY_TEMPLATES = [
    "{landmark} ke piche {locality} {cross} gali",
    "{landmark} ke paas {locality} {cross} cross",
    "{landmark} samne {locality} {cross} road",
    "{landmark} piche {locality} {cross} gali ration shop ke paas",
    "{landmark} ke peeche {locality} {cross} no gali",
    "{landmark} backside {locality} {cross} main",
    "{landmark} ke aage {locality} {cross} street",
    "{landmark} ke baad {locality} {cross} lane",
]

HINDI_TEMPLATES = [
    "{landmark} के पीछे {locality} {cross} गली",
    "{landmark} के पास {locality} {cross} क्रॉस",
    "{landmark} के सामने {locality} {cross} रोड",
]

BUILDINGS = [
    "ABC Apartments", "Sunrise Heights", "Green Valley", "Royal Enclave",
    "Shanti Nagar", "Ganesh Complex", "Krishna Residency", "Sai Apartments",
    "Laxmi Mansion", "Ganesh Tower", "Shiva Heights", "Vishnu Apartments",
]

STREETS = [
    "Main Road", "Park Street", "Gandhi Road", "Nehru Street",
    "MG Road", "Brigade Road", "Residency Road", "Lavelle Road",
    "Commercial Street", "Richmond Road", "Vittal Mallya Road",
]


def generate_pincode(city: str) -> str:
    """Generate realistic pincode for city."""
    pincodes = {
        "Bangalore": "560001",
        "Mumbai": "400001",
        "Delhi": "110001",
        "Chennai": "600001",
        "Hyderabad": "500001",
        "Pune": "411001",
        "Kolkata": "700001",
        "Ahmedabad": "380001",
    }
    base = pincodes.get(city, "110001")
    # Add some variation
    suffix = random.randint(0, 99)
    return f"{base[:-2]}{suffix:02d}"


def generate_clean_address(city: str) -> str:
    """Generate a clean, structured address."""
    template = random.choice(CLEAN_TEMPLATES)
    locality = random.choice(LOCALITIES)
    building = random.choice(BUILDINGS)
    street = random.choice(STREETS)
    pincode = generate_pincode(city)
    
    return template.format(
        num=random.randint(1, 500),
        building=building,
        locality=locality,
        city=city,
        pincode=pincode,
        street=street,
        sector=random.randint(1, 50),
    )


def generate_messy_address(city: str) -> str:
    """Generate a messy, colloquial address."""
    template = random.choice(MESSY_TEMPLATES)
    landmark = random.choice(LANDMARKS)
    locality = random.choice(LOCALITIES)
    cross = random.randint(1, 15)
    
    return template.format(
        landmark=landmark,
        locality=locality,
        cross=cross,
    )


def generate_hindi_address(city: str) -> str:
    """Generate a Hindi/Devanagari address."""
    template = random.choice(HINDI_TEMPLATES)
    landmark = random.choice(LANDMARKS)
    locality = random.choice(LOCALITIES)
    cross = random.randint(1, 15)
    
    return template.format(
        landmark=landmark,
        locality=locality,
        cross=cross,
    )


def generate_gps_noise(base_lat: float, base_lon: float, error_m: float) -> tuple[float, float]:
    """Generate GPS coordinates with specified error."""
    # Convert meters to degrees (approximate)
    lat_error = error_m / 111000
    lon_error = error_m / (111000 * math.cos(math.radians(base_lat)))
    
    lat = base_lat + random.uniform(-lat_error, lat_error)
    lon = base_lon + random.uniform(-lon_error, lon_error)
    
    return lat, lon


def generate_trajectory(
    start_lat: float, start_lon: float,
    end_lat: float, end_lon: float,
    num_points: int = 10,
    noise_m: float = 20.0
) -> list[TrajectoryPoint]:
    """Generate a realistic trajectory between two points."""
    trajectory = []
    start_time = datetime.utcnow() - timedelta(minutes=random.randint(5, 30))
    
    for i in range(num_points):
        t = i / (num_points - 1) if num_points > 1 else 0
        
        # Linear interpolation
        lat = start_lat + (end_lat - start_lat) * t
        lon = start_lon + (end_lon - start_lon) * t
        
        # Add noise
        lat, lon = generate_gps_noise(lat, lon, noise_m)
        
        # Timestamp
        timestamp = start_time + timedelta(seconds=i * random.randint(10, 60))
        
        trajectory.append(TrajectoryPoint(
            latitude=lat,
            longitude=lon,
            timestamp=timestamp,
            accuracy=random.uniform(5, 50),
            speed=random.uniform(0.5, 5.0),
        ))
    
    return trajectory


def generate_visit(
    account_id: str,
    agent_id: str,
    true_lat: float,
    true_lon: float,
    outcome: VisitOutcome,
    timestamp: datetime,
    error_m: float = 50.0,
) -> Visit:
    """Generate a visit with realistic GPS noise."""
    lat, lon = generate_gps_noise(true_lat, true_lon, error_m)
    
    # Generate trajectory for successful visits
    trajectory = []
    if outcome in [VisitOutcome.SUCCESSFUL_CONTACT, VisitOutcome.PARTIAL_CONTACT]:
        trajectory = generate_trajectory(
            true_lat, true_lon, lat, lon,
            num_points=random.randint(5, 15),
            noise_m=error_m / 2,
        )
    
    # Dwell time based on outcome
    if outcome == VisitOutcome.SUCCESSFUL_CONTACT:
        dwell = random.randint(120, 600)
    elif outcome == VisitOutcome.PARTIAL_CONTACT:
        dwell = random.randint(60, 300)
    elif outcome == VisitOutcome.FAILED_SEARCH:
        dwell = random.randint(30, 120)
    else:
        dwell = random.randint(10, 60)
    
    # Remarks
    remarks = None
    if outcome == VisitOutcome.SUCCESSFUL_CONTACT:
        remarks = random.choice([
            "Met borrower at home",
            "Borrower was available",
            "Spoke with family member",
            "Successful contact made",
        ])
    elif outcome == VisitOutcome.FAILED_SEARCH:
        remarks = random.choice([
            "Address not found",
            "House locked",
            "Locality not traceable",
            "Wrong address",
        ])
    
    return Visit(
        visit_id=f"visit_{uuid4().hex[:12]}",
        account_id=account_id,
        agent_id=agent_id,
        timestamp=timestamp,
        latitude=lat,
        longitude=lon,
        gps_accuracy=random.uniform(5, error_m),
        outcome=outcome,
        dwell_time=dwell,
        remarks=remarks,
        trajectory=trajectory,
    )


def generate_suspicious_visit(
    account_id: str,
    agent_id: str,
    timestamp: datetime,
) -> Visit:
    """Generate a suspicious/fake visit (e.g., tea shop coordinates)."""
    # Use a common meeting point (tea shop)
    tea_shop_lat = BASE_LAT + random.uniform(-0.01, 0.01)
    tea_shop_lon = BASE_LON + random.uniform(-0.01, 0.01)
    
    return Visit(
        visit_id=f"visit_{uuid4().hex[:12]}",
        account_id=account_id,
        agent_id=agent_id,
        timestamp=timestamp,
        latitude=tea_shop_lat,
        longitude=tea_shop_lon,
        gps_accuracy=random.uniform(50, 200),
        outcome=VisitOutcome.SUCCESSFUL_CONTACT,
        dwell_time=random.randint(5, 15),  # Suspiciously short
        remarks="Quick visit",
        trajectory=[],
    )


def generate_accounts(num_accounts: int = 100) -> list[Account]:
    """Generate synthetic accounts."""
    accounts = []
    
    for i in range(num_accounts):
        city = random.choice(list(CITIES.keys()))
        city_lat, city_lon = CITIES[city]
        
        # Generate address
        address_type = random.choices(
            ["clean", "messy", "hindi"],
            weights=[0.3, 0.5, 0.2]
        )[0]
        
        if address_type == "clean":
            address = generate_clean_address(city)
        elif address_type == "messy":
            address = generate_messy_address(city)
        else:
            address = generate_hindi_address(city)
        
        # True location (for evaluation)
        true_lat = city_lat + random.uniform(-0.05, 0.05)
        true_lon = city_lon + random.uniform(-0.05, 0.05)
        
        account = Account(
            account_id=f"ACC{str(i+1).zfill(6)}",
            address=address,
            language="hi" if address_type == "hindi" else "en",
            pincode=generate_pincode(city),
            locality=random.choice(LOCALITIES),
            city=city,
            state="Karnataka" if city == "Bangalore" else "Maharashtra" if city == "Mumbai" else "Delhi" if city == "Delhi" else "Tamil Nadu" if city == "Chennai" else "Telangana" if city == "Hyderabad" else "West Bengal" if city == "Kolkata" else "Gujarat",
        )
        accounts.append(account)
    
    return accounts


def generate_visits_for_account(
    account: Account,
    num_visits: int = 5,
) -> list[Visit]:
    """Generate visits for an account."""
    visits = []
    
    # Get city coordinates
    city_coords = CITIES.get(account.city, (BASE_LAT, BASE_LON))
    true_lat = city_coords[0] + random.uniform(-0.03, 0.03)
    true_lon = city_coords[1] + random.uniform(-0.03, 0.03)
    
    # Generate visits over time
    base_time = datetime.utcnow() - timedelta(days=random.randint(30, 90))
    
    for i in range(num_visits):
        timestamp = base_time + timedelta(days=i * random.randint(3, 10))
        
        # Determine outcome
        outcome = random.choices(
            [
                VisitOutcome.SUCCESSFUL_CONTACT,
                VisitOutcome.PARTIAL_CONTACT,
                VisitOutcome.FAILED_SEARCH,
                VisitOutcome.ADDRESS_NOT_TRACEABLE,
                VisitOutcome.WRONG_ADDRESS,
            ],
            weights=[0.4, 0.2, 0.2, 0.1, 0.1]
        )[0]
        
        # GPS error based on outcome
        if outcome == VisitOutcome.SUCCESSFUL_CONTACT:
            error_m = random.choice([20, 50, 100])
        elif outcome == VisitOutcome.PARTIAL_CONTACT:
            error_m = random.choice([50, 100, 200])
        else:
            error_m = random.choice([100, 200, 500, 1000])
        
        agent_id = f"AGENT{random.randint(1, 20):03d}"
        
        visit = generate_visit(
            account.account_id,
            agent_id,
            true_lat, true_lon,
            outcome,
            timestamp,
            error_m,
        )
        visits.append(visit)
    
    return visits


def generate_shared_place_accounts(num_clusters: int = 10) -> list[Account]:
    """Generate accounts that share the same physical location."""
    accounts = []
    
    for i in range(num_clusters):
        city = random.choice(list(CITIES.keys()))
        city_lat, city_lon = CITIES[city]
        
        # Shared location
        shared_lat = city_lat + random.uniform(-0.03, 0.03)
        shared_lon = city_lon + random.uniform(-0.03, 0.03)
        
        # Generate multiple address variants for same location
        for j in range(random.randint(2, 4)):
            address_type = random.choices(
                ["clean", "messy", "hindi"],
                weights=[0.2, 0.6, 0.2]
            )[0]
            
            if address_type == "clean":
                address = generate_clean_address(city)
            elif address_type == "messy":
                address = generate_messy_address(city)
            else:
                address = generate_hindi_address(city)
            
            account = Account(
                account_id=f"ACC_SHARED_{i}_{j}",
                address=address,
                language="hi" if address_type == "hindi" else "en",
                pincode=generate_pincode(city),
                locality=random.choice(LOCALITIES),
                city=city,
                state="Karnataka" if city == "Bangalore" else "Maharashtra" if city == "Mumbai" else "Delhi" if city == "Delhi" else "Tamil Nadu" if city == "Chennai" else "Telangana" if city == "Hyderabad" else "West Bengal" if city == "Kolkata" else "Gujarat",
            )
            accounts.append(account)
    
    return accounts


def main():
    """Generate and save demo data."""
    print("Initializing database...")
    init_db()
    
    print("Generating accounts...")
    accounts = generate_accounts(100)
    shared_accounts = generate_shared_place_accounts(10)
    all_accounts = accounts + shared_accounts
    
    print(f"Generated {len(all_accounts)} accounts")
    
    with db_session() as db:
        account_repo = AccountRepository(db)
        visit_repo = VisitRepository(db)
        
        print("Saving accounts...")
        for account in all_accounts:
            account_repo.create(account)
        
        print("Generating visits...")
        total_visits = 0
        for account in all_accounts:
            visits = generate_visits_for_account(account, num_visits=random.randint(3, 8))
            for visit in visits:
                visit_repo.create(visit)
                total_visits += 1
        
        print(f"Generated {total_visits} visits")
        
        # Generate some suspicious visits
        print("Generating suspicious visits...")
        for _ in range(20):
            account = random.choice(all_accounts)
            agent_id = f"AGENT{random.randint(1, 20):03d}"
            timestamp = datetime.utcnow() - timedelta(days=random.randint(1, 30))
            suspicious = generate_suspicious_visit(account.account_id, agent_id, timestamp)
            visit_repo.create(suspicious)
            total_visits += 1
        
        print(f"Total visits: {total_visits}")
    
    print("Demo data generation complete!")
    print(f"Accounts: {len(all_accounts)}")
    print(f"Visits: {total_visits}")


if __name__ == "__main__":
    main()