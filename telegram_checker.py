import asyncio
import json
import logging
import os
import pickle
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime
import re
from telethon.sync import TelegramClient, errors
from telethon.tl import types
from telethon.tl.functions.contacts import ImportContactsRequest, DeleteContactsRequest
from telethon.tl.functions.users import GetFullUserRequest

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", handlers=[logging.FileHandler("telegram_checker.log"), logging.StreamHandler()])
logger = logging.getLogger(__name__)
CONFIG_FILE = Path("config.pkl")
PROFILE_PHOTOS_DIR = Path("profile_photos")
RESULTS_DIR = Path("results")

@dataclass
class TelegramUser:
    id: int
    username: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    phone: str
    premium: bool
    verified: bool
    fake: bool
    bot: bool
    last_seen: str
    last_seen_exact: Optional[str] = None
    status_type: Optional[str] = None
    bio: Optional[str] = None
    common_chats_count: Optional[int] = None
    blocked: Optional[bool] = None
    profile_photos: Optional[List[str]] = None
    privacy_restricted: bool = False

    def __post_init__(self):
        if self.profile_photos is None:
            self.profile_photos = []

    @classmethod
    async def from_user(cls, client: TelegramClient, user: types.User, phone: str = "") -> 'TelegramUser':
        try:
            bio = ''
            common_chats_count = 0
            blocked = False

            try:
                full_user = await client(GetFullUserRequest(user.id))
                user_full_info = full_user.full_user
                bio = getattr(user_full_info, 'about', '') or ''
                common_chats_count = getattr(user_full_info, 'common_chats_count', 0)
                blocked = getattr(user_full_info, 'blocked', False)
            except:
                pass

            status_info = get_enhanced_user_status(user.status)

            return cls(
                id=user.id,
                username=user.username,
                first_name=getattr(user, 'first_name', None) or "",
                last_name=getattr(user, 'last_name', None) or "",
                phone=phone,
                premium=getattr(user, 'premium', False),
                verified=getattr(user, 'verified', False),
                fake=getattr(user, 'fake', False),
                bot=getattr(user, 'bot', False),
                last_seen=status_info['display_text'],
                last_seen_exact=status_info['exact_time'],
                status_type=status_info['status_type'],
                bio=bio,
                common_chats_count=common_chats_count,
                blocked=blocked,
                privacy_restricted=status_info['privacy_restricted'],
                profile_photos=[]
            )
        except Exception as e:
            logger.error(f"Error creating TelegramUser: {str(e)}")
            return None

def get_enhanced_user_status(status: types.TypeUserStatus) -> Dict[str, Any]:
    result = {
        'display_text': 'Unknown',
        'exact_time': None,
        'status_type': 'unknown',
        'privacy_restricted': False
    }

    if isinstance(status, types.UserStatusOnline):
        result.update({'display_text': "Currently online", 'status_type': 'online'})
    elif isinstance(status, types.UserStatusOffline):
        exact_time = status.was_online.strftime('%Y-%m-%d %H:%M:%S UTC')
        result.update({'display_text': f"Last seen: {exact_time}", 'exact_time': exact_time, 'status_type': 'offline'})
    elif isinstance(status, types.UserStatusRecently):
        result.update({'display_text': "Last seen recently", 'status_type': 'recently', 'privacy_restricted': True})
    elif isinstance(status, types.UserStatusLastWeek):
        result.update({'display_text': "Last seen within a week", 'status_type': 'last_week', 'privacy_restricted': True})
    elif isinstance(status, types.UserStatusLastMonth):
        result.update({'display_text': "Last seen within a month", 'status_type': 'last_month', 'privacy_restricted': True})
    elif status is None:
        result.update({'display_text': "Status unavailable", 'status_type': 'unavailable'})

    return result

def validate_phone_number(phone: str) -> str:
    phone = re.sub(r'[^\d+]', '', phone.strip())
    if not phone.startswith('+'): phone = '+' + phone
    if not re.match(r'^\+\d{10,15}$', phone): raise ValueError(f"Invalid phone number format: {phone}")
    return phone

def validate_username(username: str) -> str:
    username = username.strip().lstrip('@')
    if not re.match(r'^[A-Za-z0-9][A-Za-z0-9_]{3,30}[A-Za-z0-9]$|^[A-Za-z0-9_]{5,32}$', username): 
        raise ValueError(f"Invalid username format: {username}")
    return username

class TelegramChecker:
    def __init__(self):
        self.config = self.load_config()
        self.client = None
        self.needs_verification = False
        PROFILE_PHOTOS_DIR.mkdir(exist_ok=True)
        RESULTS_DIR.mkdir(exist_ok=True)

    def load_config(self) -> dict:
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, 'rb') as f: return pickle.load(f)
            except Exception as e:
                logger.error(f"Error loading config: {e}")
                return {}
        return {}

    def save_config(self):
        with open(CONFIG_FILE, 'wb') as f: pickle.dump(self.config, f)

    async def initialize(self):
        session_file = f"session_{self.config['phone'].replace('+', '')}"
        self.client = TelegramClient(session_file, self.config['api_id'], self.config['api_hash'])
        await self.client.connect()

        if not await self.client.is_user_authorized():
            await self.client.send_code_request(self.config['phone'])
            self.needs_verification = True
        else:
            self.needs_verification = False

    async def submit_code(self, code: str):
        try:
            await self.client.sign_in(self.config['phone'], code)
            self.needs_verification = False
        except errors.SessionPasswordNeededError:
            raise Exception("2FA is not supported via web yet.")

    async def download_all_profile_photos(self, user: types.User, user_data: TelegramUser):
        try:
            photos = await self.client.get_profile_photos(user)
            if not photos: return
            user_data.profile_photos = []
            for i, photo in enumerate(photos[:10]):  # Limit to 10 photos
                identifier = user_data.phone or user_data.username or str(user.id)
                safe_identifier = "".join(c for c in identifier if c.isalnum() or c in "+-_")
                photo_path = PROFILE_PHOTOS_DIR / f"{user.id}_{safe_identifier}_photo_{i}.jpg"
                await self.client.download_media(photo, file=photo_path)
                user_data.profile_photos.append(str(photo_path))
                logger.info(f"Downloaded profile photo {i+1} for user {user.id}")
        except Exception as e:
            logger.error(f"Error downloading profile photos: {str(e)}")
            user_data.profile_photos = []

    async def check_phone_number(self, phone: str) -> Optional[TelegramUser]:
        try:
            phone = validate_phone_number(phone)
            
            contact = types.InputPhoneContact(
                client_id=0,
                phone=phone,
                first_name="temp",
                last_name="contact"
            )
            
            result = await self.client(ImportContactsRequest([contact]))
            
            if result.users:
                user = result.users[0]
                if isinstance(user, types.User) and not user.deleted:
                    telegram_user = await TelegramUser.from_user(self.client, user, phone)
                    await self.download_all_profile_photos(user, telegram_user)
                    
                    try:
                        await self.client(DeleteContactsRequest([user.id]))
                    except:
                        pass
                    
                    return telegram_user
            
            try:
                await self.client(DeleteContactsRequest([]))
            except:
                pass
                
            try:
                user = await self.client.get_entity(phone)
                if isinstance(user, types.User):
                    telegram_user = await TelegramUser.from_user(self.client, user, phone)
                    await self.download_all_profile_photos(user, telegram_user)
                    return telegram_user
            except:
                pass
                
            return None
            
        except Exception as e:
            logger.error(f"Error checking phone {phone}: {str(e)}")
            return None

    async def check_username(self, username: str) -> Optional[TelegramUser]:
        try:
            username = validate_username(username)
            
            variations = [username, f"@{username}"]
            
            for variant in variations:
                try:
                    entity = await self.client.get_entity(variant)
                    if isinstance(entity, types.User):
                        telegram_user = await TelegramUser.from_user(self.client, entity, "")
                        await self.download_all_profile_photos(entity, telegram_user)
                        return telegram_user
                    elif isinstance(entity, types.Channel):
                        return None
                except errors.UsernameNotOccupiedError:
                    continue
                except errors.UsernameInvalidError:
                    continue
                except Exception as e:
                    logger.debug(f"Error with variant {variant}: {str(e)}")
                    continue
            
            return None
            
        except Exception as e:
            logger.error(f"Error checking username {username}: {str(e)}")
            return None