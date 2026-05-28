import discord
from discord.ext import commands
import os
import logging
import asyncio
import sqlite3
import traceback
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

logger = logging.getLogger('discord_bot')
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

file_handler = logging.FileHandler(os.path.join(BASE_DIR, 'bot.log'), encoding='utf-8')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix='!', intents=intents)
bot.remove_command('help')

try:
    with open(os.path.join(BASE_DIR, 'config.json'), 'r', encoding='utf-8') as _f:
        _cfg = json.load(_f)
    ALLOWED_CHANNEL_KEYWORDS = _cfg.get('allowed_channels', ['노래', '음악', 'music', '봇', 'bot'])
except Exception:
    ALLOWED_CHANNEL_KEYWORDS = ['노래', '음악', 'music', '봇', 'bot']


@bot.event
async def on_ready():
    if getattr(bot, '_initialized', False):
        logger.info(f"🔄 재연결됨: {bot.user.name}")
        return
    bot._initialized = True
    logger.info(f"✅ 로그인 성공: {bot.user.name} (ID: {bot.user.id})")
    activity = discord.Activity(type=discord.ActivityType.listening, name="!명령어")
    await bot.change_presence(status=discord.Status.online, activity=activity)

@bot.event
async def on_guild_join(guild):
    logger.info(f"서버 입장: {guild.name} (ID: {guild.id}, 멤버: {guild.member_count}명)")

@bot.event
async def on_guild_remove(guild):
    logger.info(f"서버 퇴장: {guild.name} (ID: {guild.id})")

@bot.check
async def global_channel_check(ctx):
    if isinstance(ctx.channel, discord.DMChannel):
        return False

    channel_name = ctx.channel.name.lower()
    if any(k in channel_name for k in ALLOWED_CHANNEL_KEYWORDS):
        return True

    raise commands.CheckFailure("WrongChannel")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        if str(error) == "WrongChannel":
            try:
                await ctx.message.delete()
            except discord.HTTPException:
                pass
            msg = await ctx.send(
                f"❌ 음악 봇 명령어는 지정된 채널에서만 사용할 수 있습니다.\n"
                f"*(채널 이름 예시: {', '.join(ALLOWED_CHANNEL_KEYWORDS)})*"
            )
            await asyncio.sleep(5)
            try:
                await msg.delete()
            except discord.HTTPException:
                pass
        return  # NotOwner, DM 실패 등 나머지 CheckFailure는 무시

    elif isinstance(error, commands.CommandNotFound):
        return

    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ 명령어에 필요한 값이 누락되었습니다. `!명령어`를 쳐서 사용법을 확인해주세요.")

    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ 잘못된 형식의 값을 입력하셨습니다. (예: 숫자 입력란에 텍스트 입력 등)")

    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏱️ 너무 빠릅니다. {error.retry_after:.1f}초 후 다시 시도해주세요.")

    elif isinstance(error, commands.BotMissingPermissions):
        await ctx.send(f"❌ 봇에 필요한 권한이 없습니다: `{', '.join(error.missing_permissions)}`")

    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ 이 명령어를 사용할 권한이 없습니다.")

    else:
        logger.error(f"명령어 실행 중 에러 발생 ({ctx.command}): {error}")
        traceback.print_exception(type(error), error, error.__traceback__)

@bot.event
async def on_error(event, *_args, **_kwargs):
    logger.error(f"이벤트 핸들러 오류 ({event}):", exc_info=True)


@bot.command(name='명령어', aliases=['도움', '도움말', 'help'])
async def command_list(ctx):
    embed = discord.Embed(
        title="🎵 24/7 다기능 음악 봇 v2.1",
        description="괄호 `( )` 안의 단어는 단축어로 사용할 수 있습니다.",
        color=0x00ff56
    )
    embed.add_field(
        name="🎧 기본 음악 제어",
        value="`!입장` (`!노래봇`)\n`!재생 [검색/URL]` (`!노래`)\n`!나가기` (`!나가`, `!ㅂㅂ`, `!leave`, `!disconnect`)\n`!볼륨 [0~100]` (`!v`, `!vol`)",
        inline=False
    )
    embed.add_field(
        name="📋 재생 관리",
        value="`!목록` (`!q`, `!queue`)\n`!스킵` (`!다음`, `!skip`)\n`!삭제 [번호]` (`!제거`, `!del`, `!remove`)\n`!셔플` (`!섞기`, `!shuffle`)\n`!반복` (`!1곡반복`, `!loop`), `!전체반복` (`!loopall`), `!반복종료` (`!unloop`)",
        inline=False
    )
    embed.add_field(
        name="🤖 DJ 모드 & 자동 추천",
        value="`!자동` (`!자동재생`, `!auto`) — DJ 모드 켜기\n`!자동끄기` (`!자동해제`, `!autooff`) — DJ 모드 끄기\n`!추천` (`!추천곡`, `!recommend`) — 추천곡 5개 표시\n`!상태` (`!status`, `!info`, `!정보`) — 봇 상태 확인",
        inline=False
    )
    embed.add_field(
        name="💾 개인 플레이리스트 (플리)",
        value="`!플리생성 [이름]`\n`!담기 [플리이름] [검색/URL]`\n`!플리재생` (또는 `!플리재생 [이름]`)\n`!내플리`, `!서버플리`\n`!플리내용` (`!플리목록`) (또는 `!플리내용 [이름]`)\n`!플리수정 [이름]` (일괄 삭제 지원)\n`!플리삭제`",
        inline=False
    )
    embed.add_field(
        name="🌐 플리 서버간 이동",
        value="`!플리내보내기 [이름]`\n`!플리불러오기`",
        inline=False
    )
    embed.set_footer(text="💡 재생 중 나타나는 리모컨 버튼과 플리 드롭다운 메뉴로 더 쉽게 조작하세요!")
    await ctx.send(embed=embed)

@bot.command(name='리로드', hidden=True)
@commands.is_owner()
async def reload_cogs(ctx):
    cogs_dir = os.path.join(BASE_DIR, 'cogs')
    success, failed = [], []

    try:
        for filename in os.listdir(cogs_dir):
            if filename.endswith('.py') and not filename.startswith('_'):
                cog_name = filename[:-3]
                try:
                    await bot.reload_extension(f'cogs.{cog_name}')
                    success.append(cog_name)
                    logger.info(f"엔진 리로드 성공: {cog_name}.py")
                except Exception as e:
                    failed.append(f"{cog_name} ({str(e)[:50]})")
                    logger.error(f"엔진 리로드 실패 ({cog_name}.py): {e}")

        msg = f"🔄 **엔진 실시간 리로드 결과**\n✅ 성공: {', '.join(success) if success else '없음'}"
        if failed:
            msg += f"\n❌ 실패: {', '.join(failed)}"

        await ctx.send(msg)
    except Exception as e:
        logger.error(f"리로드 명령어 실행 중 오류: {e}")
        await ctx.send(f"⚠️ 리로드 중 오류 발생: {str(e)[:100]}")


def init_master_db():
    db_path = os.path.join(BASE_DIR, 'master_index.db')
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                '''CREATE TABLE IF NOT EXISTS playlist_registry (
                   user_id TEXT,
                   playlist_name TEXT,
                   guild_id TEXT,
                   PRIMARY KEY (user_id, playlist_name))'''
            )
            conn.commit()
        logger.info("마스터 데이터베이스 검증 및 로드 완료.")
    except Exception as e:
        logger.error(f"마스터 DB 초기화 실패: {e}")

async def main():
    init_master_db()

    cogs_dir = os.path.join(BASE_DIR, 'cogs')

    async with bot:
        if os.path.exists(cogs_dir):
            for filename in os.listdir(cogs_dir):
                if filename.endswith('.py') and not filename.startswith('_'):
                    cog_name = filename[:-3]
                    try:
                        await bot.load_extension(f'cogs.{cog_name}')
                        logger.info(f"엔진 로드 성공: {cog_name}.py")
                    except Exception as e:
                        logger.error(f"엔진 로드 실패 ({cog_name}.py): {e}")
        else:
            logger.error(f"❌ cogs 폴더를 찾을 수 없습니다! (탐색 경로: {cogs_dir})")

        token_path = os.path.join(BASE_DIR, 'token.txt')
        try:
            if not os.path.exists(token_path):
                logger.error(f"❌ token.txt 파일을 찾을 수 없습니다. (탐색 경로: {token_path})")
                return

            with open(token_path, 'r', encoding='utf-8') as f:
                token = f.read().strip()

            if not token:
                logger.error("❌ token.txt 파일이 비어있습니다. 봇 토큰을 넣어주세요.")
                return

            if len(token) < 20:
                logger.error("❌ 유효하지 않은 토큰입니다. (토큰이 너무 짧음)")
                return

            logger.info("디스코드 서버에 로그인을 시도합니다...")
            await bot.start(token)

        except PermissionError:
            logger.error("❌ token.txt 파일 읽기 권한이 없습니다.")
        except UnicodeDecodeError:
            logger.error("❌ token.txt 파일 인코딩이 잘못되었습니다. (UTF-8로 저장해주세요)")
        except Exception as e:
            logger.error(f"❌ 로그인 중 오류 발생: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("봇을 수동으로 종료했습니다.")
