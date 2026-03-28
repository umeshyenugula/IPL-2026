from fastapi import FastAPI, HTTPException, Depends, status, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import FileResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from pathlib import Path
from bson import ObjectId
from dotenv import load_dotenv
import hashlib
import jwt
import os

# ─────────────────────────────────────────────
#  Config
# ─────────────────────────────────────────────
# Load variables from backend/.env when present.
load_dotenv(Path(__file__).resolve().parent / ".env")

SECRET_KEY  = os.getenv("SECRET_KEY",  "ipl2026-friends-prediction-secret-key")
ALGORITHM   = "HS256"
TOKEN_HOURS = 48
MONGO_URL   = (
    os.getenv("MONGO_URI")
    or os.getenv("MONGO_URL")
    or "mongodb://localhost:27017"
)
DB_NAME     = "ipl_prediction_2026"
FRONTEND_INDEX = Path(__file__).resolve().parent.parent / "frontend" / "index.html"

client = db = None

# ─────────────────────────────────────────────
#  DB Lifecycle
# ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(_: FastAPI):
    global client, db
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    await db.users.create_index("phone", unique=True)
    await db.predictions.create_index([("user_id",1),("match_id",1)], unique=True)
    await db.matches.create_index("match_number", unique=True)
    await seed_matches(overwrite=True)
    await seed_admin()
    try:
        yield
    finally:
        if client is not None:
            client.close()

app = FastAPI(
    title="IPL 2026 Friends Prediction",
    version="2.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)
security = HTTPBearer()

# ─────────────────────────────────────────────
#  Auth Helpers
# ─────────────────────────────────────────────
def hash_pwd(p: str) -> str:
    return hashlib.sha256(p.encode()).hexdigest()

def make_token(uid: str, role: str) -> str:
    return jwt.encode(
        {"sub": uid, "role": role, "exp": datetime.utcnow() + timedelta(hours=TOKEN_HOURS)},
        SECRET_KEY, algorithm=ALGORITHM
    )

def read_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired — please log in again")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")

def sid(doc):
    if doc and "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc

async def current_user(creds: HTTPAuthorizationCredentials = Depends(security)):
    p = read_token(creds.credentials)
    u = await db.users.find_one({"_id": ObjectId(p["sub"])})
    if not u:
        raise HTTPException(401, "User not found")
    return u

async def admin_user(u=Depends(current_user)):
    if u.get("role") != "admin":
        raise HTTPException(403, "Admin access required")
    return u

# ─────────────────────────────────────────────
#  IPL 2026 Real Schedule (70 league matches)
# ─────────────────────────────────────────────
IPL_TEAMS = {
    "RCB":  {"name":"Royal Challengers Bengaluru","short":"RCB", "color":"#EC1C24","logo":"🔴"},
    "MI":   {"name":"Mumbai Indians",             "short":"MI",  "color":"#004BA0","logo":"🔵"},
    "RR":   {"name":"Rajasthan Royals",           "short":"RR",  "color":"#254AA5","logo":"💙"},
    "PBKS": {"name":"Punjab Kings",               "short":"PBKS","color":"#ED1B24","logo":"❤️"},
    "LSG":  {"name":"Lucknow Super Giants",       "short":"LSG", "color":"#A72056","logo":"🟤"},
    "KKR":  {"name":"Kolkata Knight Riders",      "short":"KKR", "color":"#3A225D","logo":"🟣"},
    "CSK":  {"name":"Chennai Super Kings",        "short":"CSK", "color":"#F9CD1F","logo":"🟡"},
    "DC":   {"name":"Delhi Capitals",             "short":"DC",  "color":"#17479E","logo":"🔷"},
    "GT":   {"name":"Gujarat Titans",             "short":"GT",  "color":"#1C1C5E","logo":"🔹"},
    "SRH":  {"name":"Sunrisers Hyderabad",        "short":"SRH", "color":"#FF822A","logo":"🟠"},
}

# Real IPL 2026 schedule from the official PDF
REAL_SCHEDULE = [
    # Match#, date, time, home_short, away_short, venue
    (1,  "2026-03-28","19:30","RCB","SRH","M. Chinnaswamy Stadium, Bengaluru"),
    (2,  "2026-03-29","19:30","MI","KKR","Wankhede Stadium, Mumbai"),
    (3,  "2026-03-30","19:30","RR","CSK","Barsapara Cricket Stadium, Guwahati"),
    (4,  "2026-03-31","19:30","PBKS","GT","New PCA Stadium, New Chandigarh"),
    (5,  "2026-04-01","19:30","LSG","DC","BRSABV Ekana Stadium, Lucknow"),
    (6,  "2026-04-02","19:30","KKR","SRH","Eden Gardens, Kolkata"),
    (7,  "2026-04-03","19:30","CSK","PBKS","M.A. Chidambaram Stadium, Chennai"),
    (8,  "2026-04-04","15:30","DC","MI","Arun Jaitley Stadium, Delhi"),
    (9,  "2026-04-04","19:30","GT","RR","Narendra Modi Stadium, Ahmedabad"),
    (10, "2026-04-05","15:30","SRH","LSG","Rajiv Gandhi Intl. Stadium, Hyderabad"),
    (11, "2026-04-05","19:30","RCB","CSK","M. Chinnaswamy Stadium, Bengaluru"),
    (12, "2026-04-06","19:30","KKR","PBKS","Eden Gardens, Kolkata"),
    (13, "2026-04-07","19:30","RR","MI","Barsapara Cricket Stadium, Guwahati"),
    (14, "2026-04-08","19:30","DC","GT","Arun Jaitley Stadium, Delhi"),
    (15, "2026-04-09","19:30","KKR","LSG","Eden Gardens, Kolkata"),
    (16, "2026-04-10","19:30","RR","RCB","Barsapara Cricket Stadium, Guwahati"),
    (17, "2026-04-11","15:30","PBKS","SRH","New PCA Stadium, New Chandigarh"),
    (18, "2026-04-11","19:30","CSK","DC","M.A. Chidambaram Stadium, Chennai"),
    (19, "2026-04-12","15:30","LSG","GT","BRSABV Ekana Stadium, Lucknow"),
    (20, "2026-04-12","19:30","MI","RCB","Wankhede Stadium, Mumbai"),
    (21, "2026-04-13","19:30","SRH","RR","Rajiv Gandhi Intl. Stadium, Hyderabad"),
    (22, "2026-04-14","19:30","CSK","KKR","M.A. Chidambaram Stadium, Chennai"),
    (23, "2026-04-15","19:30","RCB","LSG","M. Chinnaswamy Stadium, Bengaluru"),
    (24, "2026-04-16","19:30","MI","PBKS","Wankhede Stadium, Mumbai"),
    (25, "2026-04-17","19:30","GT","KKR","Narendra Modi Stadium, Ahmedabad"),
    (26, "2026-04-18","15:30","RCB","DC","M. Chinnaswamy Stadium, Bengaluru"),
    (27, "2026-04-18","19:30","SRH","CSK","Rajiv Gandhi Intl. Stadium, Hyderabad"),
    (28, "2026-04-19","15:30","KKR","RR","Eden Gardens, Kolkata"),
    (29, "2026-04-19","19:30","PBKS","LSG","New PCA Stadium, New Chandigarh"),
    (30, "2026-04-20","19:30","GT","MI","Narendra Modi Stadium, Ahmedabad"),
    (31, "2026-04-21","19:30","SRH","DC","Rajiv Gandhi Intl. Stadium, Hyderabad"),
    (32, "2026-04-22","19:30","LSG","RR","BRSABV Ekana Stadium, Lucknow"),
    (33, "2026-04-23","19:30","MI","CSK","Wankhede Stadium, Mumbai"),
    (34, "2026-04-24","19:30","RCB","GT","M. Chinnaswamy Stadium, Bengaluru"),
    (35, "2026-04-25","15:30","DC","PBKS","Arun Jaitley Stadium, Delhi"),
    (36, "2026-04-25","19:30","RR","SRH","Sawai Mansingh Stadium, Jaipur"),
    (37, "2026-04-26","15:30","GT","CSK","Narendra Modi Stadium, Ahmedabad"),
    (38, "2026-04-26","19:30","LSG","KKR","BRSABV Ekana Stadium, Lucknow"),
    (39, "2026-04-27","19:30","DC","RCB","Arun Jaitley Stadium, Delhi"),
    (40, "2026-04-28","19:30","PBKS","RR","New PCA Stadium, New Chandigarh"),
    (41, "2026-04-29","19:30","MI","SRH","Wankhede Stadium, Mumbai"),
    (42, "2026-04-30","19:30","GT","RCB","Narendra Modi Stadium, Ahmedabad"),
    (43, "2026-05-01","19:30","RR","DC","Sawai Mansingh Stadium, Jaipur"),
    (44, "2026-05-02","19:30","CSK","MI","M.A. Chidambaram Stadium, Chennai"),
    (45, "2026-05-03","15:30","SRH","KKR","Rajiv Gandhi Intl. Stadium, Hyderabad"),
    (46, "2026-05-03","19:30","GT","PBKS","Narendra Modi Stadium, Ahmedabad"),
    (47, "2026-05-04","19:30","MI","LSG","Wankhede Stadium, Mumbai"),
    (48, "2026-05-05","19:30","DC","CSK","Arun Jaitley Stadium, Delhi"),
    (49, "2026-05-06","19:30","SRH","PBKS","Rajiv Gandhi Intl. Stadium, Hyderabad"),
    (50, "2026-05-07","19:30","LSG","RCB","BRSABV Ekana Stadium, Lucknow"),
    (51, "2026-05-08","19:30","DC","KKR","Arun Jaitley Stadium, Delhi"),
    (52, "2026-05-09","19:30","RR","GT","Sawai Mansingh Stadium, Jaipur"),
    (53, "2026-05-10","15:30","CSK","LSG","M.A. Chidambaram Stadium, Chennai"),
    (54, "2026-05-10","19:30","RCB","MI","Shaheed Veer Narayan Singh Stadium, Raipur"),
    (55, "2026-05-11","19:30","PBKS","DC","HPCA Stadium, Dharamshala"),
    (56, "2026-05-12","19:30","GT","SRH","Narendra Modi Stadium, Ahmedabad"),
    (57, "2026-05-13","19:30","RCB","KKR","Shaheed Veer Narayan Singh Stadium, Raipur"),
    (58, "2026-05-14","19:30","PBKS","MI","HPCA Stadium, Dharamshala"),
    (59, "2026-05-15","19:30","LSG","CSK","BRSABV Ekana Stadium, Lucknow"),
    (60, "2026-05-16","19:30","KKR","GT","Eden Gardens, Kolkata"),
    (61, "2026-05-17","15:30","PBKS","RCB","HPCA Stadium, Dharamshala"),
    (62, "2026-05-17","19:30","DC","RR","Arun Jaitley Stadium, Delhi"),
    (63, "2026-05-18","19:30","CSK","SRH","M.A. Chidambaram Stadium, Chennai"),
    (64, "2026-05-19","19:30","RR","LSG","Sawai Mansingh Stadium, Jaipur"),
    (65, "2026-05-20","19:30","KKR","MI","Eden Gardens, Kolkata"),
    (66, "2026-05-21","19:30","CSK","GT","M.A. Chidambaram Stadium, Chennai"),
    (67, "2026-05-22","19:30","SRH","RCB","Rajiv Gandhi Intl. Stadium, Hyderabad"),
    (68, "2026-05-23","19:30","LSG","PBKS","BRSABV Ekana Stadium, Lucknow"),
    (69, "2026-05-24","15:30","MI","RR","Wankhede Stadium, Mumbai"),
    (70, "2026-05-24","19:30","KKR","DC","Eden Gardens, Kolkata"),
    # Playoffs (TBD venues)
    (71, "2026-05-27","19:30","TBD1","TBD2","TBD Venue"),
    (72, "2026-05-29","19:30","TBD1","TBD2","TBD Venue - IPL Final"),
]

TBD_TEAM = {"name":"TBD","short":"TBD","color":"#888","logo":"🏏"}

async def seed_matches(overwrite: bool = False):
    count = await db.matches.count_documents({})
    if count > 0 and not overwrite:
        return

    docs = []
    for row in REAL_SCHEDULE:
        num, date, time, h, a, venue = row
        t1 = IPL_TEAMS.get(h, TBD_TEAM)
        t2 = IPL_TEAMS.get(a, TBD_TEAM)
        docs.append({
            "match_number": num,
            "title": f"Match {num}",
            "team1": t1,
            "team2": t2,
            "venue": venue,
            "match_date": date,
            "match_time": time,
            "status": "upcoming",
            "voting_open": True,
            "result_winner": None,
            "created_at": datetime.utcnow().isoformat(),
        })

    if overwrite:
        valid_match_numbers = [d["match_number"] for d in docs]
        for doc in docs:
            await db.matches.replace_one(
                {"match_number": doc["match_number"]},
                doc,
                upsert=True,
            )
        removed = await db.matches.delete_many({"match_number": {"$nin": valid_match_numbers}})
        print(
            f"✅ Real IPL 2026 schedule synced: {len(docs)} matches upserted, "
            f"{removed.deleted_count} old matches removed"
        )
        return

    await db.matches.insert_many(docs)
    print(f"✅ Seeded {len(docs)} IPL 2026 matches")

async def seed_admin():
    if not await db.users.find_one({"phone": "9999999999"}):
        await db.users.insert_one({
            "name": "IPL Admin",
            "phone": "9999999999",
            "password": hash_pwd("admin@ipl2026"),
            "role": "admin",
            "created_at": datetime.utcnow().isoformat(),
        })
        print("✅ Admin → phone:9999999999  pass:admin@ipl2026")

# ─────────────────────────────────────────────
#  Request Models
# ─────────────────────────────────────────────
class RegisterReq(BaseModel):
    name: str
    phone: str
    password: str

class LoginReq(BaseModel):
    phone: str
    password: str

class PredictionReq(BaseModel):
    match_id: str
    predicted_winner: str

class ResultReq(BaseModel):
    winner: str

class VotingReq(BaseModel):
    voting_open: bool

class StatusReq(BaseModel):
    status: str  # upcoming | live | completed

# ─────────────────────────────────────────────
#  Auth Routes
# ─────────────────────────────────────────────
@app.post("/api/auth/register")
async def register(req: RegisterReq):
    if await db.users.find_one({"phone": req.phone}):
        raise HTTPException(400, "Phone number already registered")
    if len(req.phone) != 10 or not req.phone.isdigit():
        raise HTTPException(400, "Enter a valid 10-digit phone number")
    if len(req.name.strip()) < 2:
        raise HTTPException(400, "Name is too short")
    if len(req.password) < 4:
        raise HTTPException(400, "Password must be at least 4 characters")
    doc = {
        "name": req.name.strip(),
        "phone": req.phone,
        "password": hash_pwd(req.password),
        "role": "voter",
        "created_at": datetime.utcnow().isoformat(),
    }
    r = await db.users.insert_one(doc)
    token = make_token(str(r.inserted_id), "voter")
    return {"message": "Registration successful! Welcome to the league!", "token": token,
            "name": req.name.strip(), "role": "voter", "user_id": str(r.inserted_id)}

@app.post("/api/auth/login")
async def login(req: LoginReq):
    u = await db.users.find_one({"phone": req.phone})
    if not u or u["password"] != hash_pwd(req.password):
        raise HTTPException(401, "Invalid phone or password")
    token = make_token(str(u["_id"]), u["role"])
    return {"message": "Login successful", "token": token,
            "name": u["name"], "role": u["role"], "user_id": str(u["_id"])}

@app.get("/api/auth/me")
async def me(u=Depends(current_user)):
    return {"name": u["name"], "phone": u["phone"], "role": u["role"], "id": str(u["_id"])}

# ─────────────────────────────────────────────
#  Match Routes
# ─────────────────────────────────────────────
@app.get("/api/matches")
async def get_matches(status: Optional[str] = None):
    q = {}
    if status:
        q["status"] = status
    cursor = db.matches.find(q).sort("match_number", 1)
    return [sid(m) async for m in cursor]

@app.get("/api/matches/today")
async def today_matches():
    today = datetime.utcnow().date().isoformat()
    cursor = db.matches.find({"match_date": today}).sort("match_number", 1)
    return [sid(m) async for m in cursor]

@app.get("/api/matches/{match_id}")
async def get_match(match_id: str):
    m = await db.matches.find_one({"_id": ObjectId(match_id)})
    if not m:
        raise HTTPException(404, "Match not found")
    return sid(m)

# ─────────────────────────────────────────────
#  Prediction Routes
# ─────────────────────────────────────────────
@app.post("/api/predictions")
async def predict(req: PredictionReq, u=Depends(current_user)):
    m = await db.matches.find_one({"_id": ObjectId(req.match_id)})
    if not m:
        raise HTTPException(404, "Match not found")
    if not m.get("voting_open"):
        raise HTTPException(400, "Voting is closed for this match")
    if m.get("status") == "completed":
        raise HTTPException(400, "Match already completed — cannot predict")
    if req.predicted_winner not in [m["team1"]["short"], m["team2"]["short"]]:
        raise HTTPException(400, "Invalid team selection")
    # One-shot — no modifications
    if await db.predictions.find_one({"user_id": str(u["_id"]), "match_id": req.match_id}):
        raise HTTPException(400, "You already predicted this match — no modifications allowed!")
    doc = {
        "user_id": str(u["_id"]),
        "user_name": u["name"],
        "match_id": req.match_id,
        "match_number": m["match_number"],
        "predicted_winner": req.predicted_winner,
        "actual_winner": None,
        "is_correct": None,
        "created_at": datetime.utcnow().isoformat(),
    }
    await db.predictions.insert_one(doc)
    return {"message": f"Prediction saved: {req.predicted_winner}. No modifications allowed!", "predicted": req.predicted_winner}

@app.get("/api/predictions/my")
async def my_predictions(u=Depends(current_user)):
    cursor = db.predictions.find({"user_id": str(u["_id"])}).sort("match_number", 1)
    return [sid(p) async for p in cursor]

@app.get("/api/predictions/match/{match_id}")
async def match_predictions(match_id: str, u=Depends(current_user)):
    cursor = db.predictions.find({"match_id": match_id})
    return [sid(p) async for p in cursor]

# ─────────────────────────────────────────────
#  Leaderboard
# ─────────────────────────────────────────────
@app.get("/api/leaderboard")
async def leaderboard():
    pipeline = [
        {"$group": {
            "_id": "$user_id",
            "user_name": {"$first": "$user_name"},
            "total_predictions": {"$sum": 1},
            "correct": {"$sum": {"$cond": [{"$eq": ["$is_correct", True]}, 1, 0]}},
            "wrong":   {"$sum": {"$cond": [{"$eq": ["$is_correct", False]}, 1, 0]}},
            "pending": {"$sum": {"$cond": [{"$eq": ["$is_correct", None]}, 1, 0]}},
        }},
        {"$addFields": {
            "decided": {"$subtract": ["$total_predictions", "$pending"]},
            "accuracy": {"$cond": [
                {"$gt": [{"$subtract": ["$total_predictions","$pending"]}, 0]},
                {"$multiply": [{"$divide": ["$correct", {"$subtract": ["$total_predictions","$pending"]}]}, 100]},
                0
            ]}
        }},
        {"$sort": {"correct": -1, "accuracy": -1}},
        {"$limit": 100},
    ]
    return [r async for r in db.predictions.aggregate(pipeline)]

# ─────────────────────────────────────────────
#  Admin Routes
# ─────────────────────────────────────────────
@app.put("/api/admin/matches/{match_id}/result")
async def set_result(match_id: str, req: ResultReq, _=Depends(admin_user)):
    m = await db.matches.find_one({"_id": ObjectId(match_id)})
    if not m:
        raise HTTPException(404, "Match not found")
    if req.winner not in [m["team1"]["short"], m["team2"]["short"]]:
        raise HTTPException(400, "Invalid winner — must be one of the playing teams")
    await db.matches.update_one(
        {"_id": ObjectId(match_id)},
        {"$set": {"result_winner": req.winner, "status": "completed", "voting_open": False}}
    )
    # Score all predictions for this match
    await db.predictions.update_many(
        {"match_id": match_id, "actual_winner": None},
        [{"$set": {
            "actual_winner": req.winner,
            "is_correct": {"$eq": ["$predicted_winner", req.winner]}
        }}]
    )
    return {"message": f"Result set: {req.winner} wins! All predictions scored."}

@app.put("/api/admin/matches/{match_id}/voting")
async def toggle_voting(match_id: str, req: VotingReq, _=Depends(admin_user)):
    r = await db.matches.update_one(
        {"_id": ObjectId(match_id)},
        {"$set": {"voting_open": req.voting_open}}
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Match not found")
    return {"message": f"Voting {'opened' if req.voting_open else 'closed'}"}

@app.put("/api/admin/matches/{match_id}/status")
async def update_status(match_id: str, req: StatusReq, _=Depends(admin_user)):
    if req.status not in ["upcoming", "live", "completed"]:
        raise HTTPException(400, "status must be: upcoming | live | completed")
    await db.matches.update_one({"_id": ObjectId(match_id)}, {"$set": {"status": req.status}})
    return {"message": f"Match status → {req.status}"}

@app.get("/api/admin/stats")
async def admin_stats(_=Depends(admin_user)):
    total_users     = await db.users.count_documents({"role": "voter"})
    total_matches   = await db.matches.count_documents({})
    completed       = await db.matches.count_documents({"status": "completed"})
    live            = await db.matches.count_documents({"status": "live"})
    total_preds     = await db.predictions.count_documents({})
    return {
        "total_users": total_users,
        "total_matches": total_matches,
        "completed_matches": completed,
        "live_matches": live,
        "upcoming_matches": total_matches - completed - live,
        "total_predictions": total_preds,
    }

@app.get("/api/admin/users")
async def all_users(_=Depends(admin_user)):
    cursor = db.users.find({"role": "voter"}).sort("created_at", -1)
    users = []
    async for u in cursor:
        u["_id"] = str(u["_id"])
        u.pop("password", None)
        users.append(u)
    return users

@app.get("/")
async def root():
    if FRONTEND_INDEX.exists():
        return FileResponse(FRONTEND_INDEX)
    return {"message": "IPL 2026 Friends Prediction API v2.0", "docs": "/docs", "matches": 72}
