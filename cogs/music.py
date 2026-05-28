import discord
from discord.ext import commands
import yt_dlp
import asyncio
import os
import random
import json
import logging
import math
import time
from typing import Optional, Dict, List

logger = logging.getLogger('discord_bot')


class PageView(discord.ui.View):
    def __init__(self, pages: list, author_id: int):
        super().__init__(timeout=60)
        self.pages = pages
        self.author_id = author_id
        self.page = 0
        self._refresh()

    def _refresh(self):
        self.prev_btn.disabled = (self.page == 0)
        self.next_btn.disabled = (self.page >= len(self.pages) - 1)

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.grey)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("❌ 명령어 실행자만 조작할 수 있습니다.", ephemeral=True)
        self.page -= 1
        self._refresh()
        await interaction.response.edit_message(embed=self.pages[self.page], view=self)

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.grey)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("❌ 명령어 실행자만 조작할 수 있습니다.", ephemeral=True)
        self.page += 1
        self._refresh()
        await interaction.response.edit_message(embed=self.pages[self.page], view=self)


class MusicControlView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="⏯️ 재생/일시정지", style=discord.ButtonStyle.grey)
    async def play_pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer(ephemeral=True)
            vc = interaction.guild.voice_client
            if not vc:
                return await interaction.followup.send("❌ 연결된 채널이 없습니다.")

            if vc.is_paused():
                vc.resume()
                await interaction.followup.send("▶️ 다시 재생합니다.")
            elif vc.is_playing():
                vc.pause()
                await interaction.followup.send("⏸️ 일시정지합니다.")
            else:
                await interaction.followup.send("❓ 재생 중인 곡이 없습니다.")
        except discord.errors.NotFound:
            pass
        except Exception as e:
            logger.error(f"[MusicCog] 재생/일시정지 버튼 오류: {e}")

    @discord.ui.button(label="⏭️ 스킵", style=discord.ButtonStyle.blurple)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer(ephemeral=True)
            vc = interaction.guild.voice_client
            gid = interaction.guild.id
            if vc and vc.is_playing():
                if self.cog.repeat_mode.get(gid) == 'one':
                    self.cog.current_song.pop(gid, None)
                vc.stop()
                await interaction.followup.send("⏭️ 현재 곡을 건너뜁니다.")
            else:
                await interaction.followup.send("❌ 스킵할 곡이 없습니다.")
        except discord.errors.NotFound:
            pass
        except Exception as e:
            logger.error(f"[MusicCog] 스킵 버튼 오류: {e}")

    @discord.ui.button(label="🔀 셔플", style=discord.ButtonStyle.green)
    async def shuffle(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer(ephemeral=True)
            gid = interaction.guild.id
            if gid in self.cog.queue and len(self.cog.queue[gid]) > 1:
                random.shuffle(self.cog.queue[gid])
                await interaction.followup.send(f"🔀 현재 대기열 {len(self.cog.queue[gid])}곡을 섞었습니다!")
            else:
                await interaction.followup.send("📭 섞을 곡이 부족합니다.")
        except discord.errors.NotFound:
            pass
        except Exception as e:
            logger.error(f"[MusicCog] 셔플 버튼 오류: {e}")

    @discord.ui.button(label="🔁 반복 모드", style=discord.ButtonStyle.grey)
    async def cycle_repeat(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer(ephemeral=True)
            gid = interaction.guild.id
            modes = ['none', 'one', 'all']
            current = self.cog.repeat_mode.get(gid, 'none')
            new_mode = modes[(modes.index(current) + 1) % 3]
            self.cog.repeat_mode[gid] = new_mode
            mode_text = {"none": "❌ 반복 안 함", "one": "🔂 1곡 반복", "all": "🔁 전체 반복"}
            await interaction.followup.send(f"🔄 반복 모드 변경: **{mode_text[new_mode]}**")
        except discord.errors.NotFound:
            pass
        except Exception as e:
            logger.error(f"[MusicCog] 반복 모드 버튼 오류: {e}")

    @discord.ui.button(label="⏹️ 나가기", style=discord.ButtonStyle.red)
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer(ephemeral=True)
            vc = interaction.guild.voice_client
            if vc:
                gid = interaction.guild.id
                prev_msg = self.cog.now_playing_msg.pop(gid, None)
                task = self.cog.alone_timers.pop(gid, None)
                if task:
                    task.cancel()
                self.cog.queue.pop(gid, None)
                self.cog.repeat_mode.pop(gid, None)
                self.cog.current_song.pop(gid, None)
                self.cog.played_songs.pop(gid, None)
                self.cog.dj_mode.pop(gid, None)
                await vc.disconnect()
                if prev_msg:
                    try:
                        await prev_msg.delete()
                    except Exception:
                        pass
                await interaction.followup.send("⏹️ 연결을 종료합니다.")
            else:
                await interaction.followup.send("❌ 채널에 있지 않습니다.")
        except discord.errors.NotFound:
            pass
        except Exception as e:
            logger.error(f"[MusicCog] 나가기 버튼 오류: {e}")


class MusicCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.queue: Dict[int, List[Dict[str, str]]] = {}
        self.repeat_mode: Dict[int, str] = {}
        self.current_song: Dict[int, Dict[str, str]] = {}
        self.played_songs: Dict[int, List[Dict[str, str]]] = {}
        self.now_playing_msg: Dict[int, discord.Message] = {}
        self.alone_timers: Dict[int, asyncio.Task] = {}
        self.dj_mode: Dict[int, bool] = {}
        self.last_recommended: Dict[int, set] = {}
        self.artist_count: Dict[int, Dict[str, int]] = {}
        self.volume: Dict[int, float] = {}

        config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.json')
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)

            required_keys = ['ytdl_opts', 'ffmpeg_options', 'default_volume']
            for key in required_keys:
                if key not in config:
                    raise ValueError(f"config.json에 '{key}' 키가 없습니다.")

            if not isinstance(config['default_volume'], (int, float)) or not (0 <= config['default_volume'] <= 1):
                raise ValueError("default_volume은 0~1 사이의 숫자여야 합니다.")

        except (FileNotFoundError, json.JSONDecodeError, ValueError) as e:
            logger.warning(f"[MusicCog] 설정 파일 오류: {e}. 기본 설정을 사용합니다.")
            config = {
                "ytdl_opts": {
                    'format': 'bestaudio/best',
                    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
                    'restrictfilenames': True,
                    'noplaylist': True,
                    'nocheckcertificate': True,
                    'ignoreerrors': False,
                    'logtostderr': False,
                    'quiet': True,
                    'no_warnings': True,
                    'default_search': 'auto',
                    'source_address': '0.0.0.0',
                },
                "ffmpeg_options": {
                    'before_options': '-reconnect 1 -reconnect_at_eof 1 -reconnect_streamed 1 -reconnect_delay_max 5',
                    'options': '-vn -b:a 128k',
                },
                "default_volume": 0.5,
            }

        self.ytdl_opts = config["ytdl_opts"]
        self.ffmpeg_options = config["ffmpeg_options"]
        self._default_volume: float = config["default_volume"]
        self.dj_config = config.get("dj_mode", {
            "recommend_count": 10,
            "max_artists": 10,
            "songs_per_artist": 3,
            "use_playlist_first": True,
            "fallback_to_history": True,
        })
        self.ytdl = yt_dlp.YoutubeDL(self.ytdl_opts)

    async def cog_load(self):
        self._cleanup_task = asyncio.create_task(self._memory_cleanup_task())

    async def cog_unload(self):
        task = getattr(self, '_cleanup_task', None)
        if task:
            task.cancel()
        for t in self.alone_timers.values():
            t.cancel()
        self.alone_timers.clear()

    def _get_volume(self, gid: int) -> float:
        return self.volume.get(gid, self._default_volume)

    async def _memory_cleanup_task(self):
        while True:
            await asyncio.sleep(3600)
            current_time = time.time()

            to_remove = []
            for gid, msg in self.now_playing_msg.items():
                if hasattr(msg, 'created_at') and (current_time - msg.created_at.timestamp()) > 86400:
                    to_remove.append(gid)

            for gid in to_remove:
                try:
                    await self.now_playing_msg[gid].delete()
                except Exception:
                    pass
                del self.now_playing_msg[gid]

            inactive_guilds = [
                gid for gid in self.queue
                if not self.queue[gid] and gid not in self.current_song and gid not in self.now_playing_msg
            ]
            for gid in inactive_guilds:
                self._cleanup_guild_data(gid)

            logger.info(f"[MusicCog] 메모리 정리 완료: {len(to_remove)} 메시지, {len(inactive_guilds)} 길드")

    def _extract_artist(self, song_title: str) -> Optional[str]:
        if ' - ' in song_title:
            return song_title.split(' - ')[0].strip()
        return None

    async def _get_recommended_songs(self, user_id: int, guild_id: int, current_song_title: str, count: int = 10) -> List[Dict[str, str]]:
        try:
            database_cog = self.bot.get_cog('DatabaseCog')
            if not database_cog:
                logger.warning("[MusicCog] DJ 모드: DatabaseCog 로드 실패")
                return []

            recommended_artists = []

            if self.dj_config.get("use_playlist_first"):
                uid_str, gid_str = str(user_id), str(guild_id)
                playlists = database_cog.get_user_playlists(uid_str)
                artist_count = {}
                for playlist in playlists:
                    songs = database_cog.get_playlist_songs(uid_str, playlist, gid_str)
                    for song in songs:
                        artist = self._extract_artist(song)
                        if artist:
                            artist_count[artist] = artist_count.get(artist, 0) + 1
                if artist_count:
                    recommended_artists = sorted(artist_count.items(), key=lambda x: x[1], reverse=True)[:self.dj_config.get("max_artists", 10)]

            if not recommended_artists and self.dj_config.get("fallback_to_history"):
                uid_str, gid_str = str(user_id), str(guild_id)
                play_history = database_cog.get_play_history(uid_str, gid_str, self.dj_config.get("max_artists", 10))
                recommended_artists = [(h['artist'], h['play_count']) for h in play_history]

            if not recommended_artists:
                fallback_keywords = ["유명한 팝송", "빌보드 핫 100", "Jpop 인기곡", "Kpop 최신곡", "신나는 플레이리스트", "감성 발라드"]
                random.shuffle(fallback_keywords)
                recommended_artists = [(kw, 1) for kw in fallback_keywords[:5]]

            if guild_id not in self.last_recommended:
                self.last_recommended[guild_id] = set()
            if guild_id not in self.artist_count:
                self.artist_count[guild_id] = {}

            if len(self.artist_count[guild_id]) > 30:
                self.artist_count[guild_id].clear()

            recommendations = []
            suffixes = ["명곡", "인기곡", "라이브", "MV", "official audio", "노래 모음"]
            for artist, _ in recommended_artists:
                if self.artist_count[guild_id].get(artist, 0) >= self.dj_config.get("songs_per_artist", 3):
                    continue
                try:
                    song_info = await self.fetch_info(f"{artist} {random.choice(suffixes)}")
                    if song_info and song_info['url'] not in self.last_recommended[guild_id]:
                        recommendations.append(song_info)
                        self.last_recommended[guild_id].add(song_info['url'])
                        self.artist_count[guild_id][artist] = self.artist_count[guild_id].get(artist, 0) + 1
                        if len(recommendations) >= count:
                            break
                except Exception as e:
                    logger.error(f"[MusicCog] DJ 모드 곡 검색 오류 ({artist}): {e}")

            if len(self.last_recommended[guild_id]) > 100:
                self.last_recommended[guild_id].clear()

            return recommendations

        except Exception as e:
            logger.error(f"[MusicCog] DJ 모드 추천 알고리즘 오류: {e}")
            return []

    async def fetch_info(self, search: str) -> Optional[Dict[str, str]]:
        try:
            data = await self.bot.loop.run_in_executor(
                None, lambda: self.ytdl.extract_info(search, download=False)
            )
            if 'entries' in data:
                if not data['entries']:
                    return None
                data = data['entries'][0]
            return {'url': data['url'], 'title': data['title'], 'original': search}
        except yt_dlp.utils.DownloadError as e:
            logger.error(f"[MusicCog] 다운로드 오류: {e}")
            return None
        except yt_dlp.utils.ExtractorError as e:
            logger.error(f"[MusicCog] 추출기 오류: {e}")
            return None
        except Exception as e:
            logger.error(f"[MusicCog] 곡 정보 추출 오류: {e}")
            return None

    def _handle_repeat_mode(self, gid: int):
        if self.repeat_mode.get(gid) == 'one' and self.current_song.get(gid):
            self.queue.setdefault(gid, []).insert(0, self.current_song[gid])
        elif self.repeat_mode.get(gid) == 'all' and self.current_song.get(gid):
            self.played_songs.setdefault(gid, []).append(self.current_song[gid])

    def _prepare_next_queue(self, gid: int):
        if not self.queue.get(gid) and self.repeat_mode.get(gid) == 'all':
            if self.played_songs.get(gid):
                self.queue[gid] = self.played_songs[gid]
                self.played_songs[gid] = []

    def _cleanup_guild_data(self, gid: int):
        self.current_song.pop(gid, None)
        self.played_songs.pop(gid, None)
        self.repeat_mode.pop(gid, None)
        self.queue.pop(gid, None)
        self.dj_mode.pop(gid, None)
        self.last_recommended.pop(gid, None)
        self.artist_count.pop(gid, None)
        self.volume.pop(gid, None)
        task = self.alone_timers.pop(gid, None)
        if task:
            task.cancel()
        msg = self.now_playing_msg.pop(gid, None)
        if msg:
            try:
                asyncio.run_coroutine_threadsafe(msg.delete(), self.bot.loop)
            except Exception:
                pass

    def play_next(self, ctx: commands.Context):
        try:
            if not ctx or not ctx.guild:
                return

            gid = ctx.guild.id
            self._handle_repeat_mode(gid)
            self._prepare_next_queue(gid)

            if self.queue.get(gid):
                if self.dj_mode.get(gid, False) and len(self.queue[gid]) <= 5:
                    async def fill_queue():
                        needed = 10 - len(self.queue[gid])
                        recs = await self._get_recommended_songs(
                            ctx.author.id, gid, self.current_song.get(gid, {}).get('title', ''), needed
                        )
                        for rec in recs:
                            self.queue[gid].append({'original_search': rec['url'], 'title': rec['title']})
                    asyncio.run_coroutine_threadsafe(fill_queue(), self.bot.loop)

                asyncio.run_coroutine_threadsafe(self._process_play(ctx), self.bot.loop)

            elif self.dj_mode.get(gid, False):
                current_title = self.current_song.get(gid, {}).get('title', '')
                async def auto_recommend():
                    recs = await self._get_recommended_songs(ctx.author.id, gid, current_title, 10)
                    if recs:
                        for rec in recs:
                            self.queue[gid].append({'original_search': rec['url'], 'title': rec['title']})
                        asyncio.run_coroutine_threadsafe(self._process_play(ctx), self.bot.loop)
                    else:
                        self._cleanup_guild_data(gid)
                asyncio.run_coroutine_threadsafe(auto_recommend(), self.bot.loop)
            else:
                self._cleanup_guild_data(gid)

        except Exception as e:
            logger.error(f"[MusicCog] play_next 오류: {e}")

    async def _process_play(self, ctx: commands.Context):
        gid = ctx.guild.id

        if not self.queue.get(gid):
            self.current_song.pop(gid, None)
            return

        song_info = self.queue[gid].pop(0)
        self.current_song[gid] = song_info

        try:
            data = await self.fetch_info(song_info['original_search'])

            if not data:
                await ctx.send(f"⚠️ 곡 정보를 불러올 수 없어 건너뜁니다: **{song_info['title']}**")
                self.current_song.pop(gid, None)
                return self.play_next(ctx)

            vc = ctx.guild.voice_client
            if not vc:
                return

            vol = self._get_volume(gid)
            source = discord.FFmpegPCMAudio(data['url'], **self.ffmpeg_options)
            player = discord.PCMVolumeTransformer(source, volume=vol)
            vc.play(player, after=lambda e: self.play_next(ctx))

            database_cog = self.bot.get_cog('DatabaseCog')
            if database_cog:
                artist = self._extract_artist(data['title'])
                database_cog.add_to_play_history(str(ctx.author.id), str(gid), data['title'], data['url'], artist)

            prev_msg = self.now_playing_msg.pop(gid, None)
            if prev_msg:
                try:
                    await prev_msg.delete()
                except Exception:
                    pass

            mode_icons = {"none": "", "one": " 🔂", "all": " 🔁"}
            icon = mode_icons.get(self.repeat_mode.get(gid, 'none'), "")
            dj_icon = " 🎵자동" if self.dj_mode.get(gid, False) else ""

            embed = discord.Embed(
                title=f"🎶 현재 재생 중{icon}{dj_icon}",
                description=f"**[{data['title']}]({data['url']})**",
                color=0x00ff56
            )
            embed.add_field(name="볼륨", value=f"{int(vol * 100)}%", inline=True)
            embed.add_field(name="대기열", value=f"{len(self.queue.get(gid, []))}곡 남음", inline=True)

            msg = await ctx.send(embed=embed, view=MusicControlView(self))
            self.now_playing_msg[gid] = msg

        except discord.Forbidden:
            self.current_song.pop(gid, None)
        except Exception as e:
            logger.error(f"[MusicCog] 재생 중 오류: {e}")
            self.current_song.pop(gid, None)
            await asyncio.sleep(1)
            self.play_next(ctx)

    async def add_songs(self, interaction_or_ctx, songs_list: List[Dict[str, str]]):
        gid = interaction_or_ctx.guild.id
        self.queue.setdefault(gid, [])

        for s in songs_list:
            self.queue[gid].append({'original_search': s['target'], 'title': s['title']})

        voice = interaction_or_ctx.guild.voice_client
        if voice and not voice.is_playing() and not voice.is_paused():
            if isinstance(interaction_or_ctx, discord.Interaction):
                try:
                    msg = interaction_or_ctx.message
                    if msg is None:
                        return
                    ctx = await self.bot.get_context(msg)
                    if ctx and ctx.guild:
                        self.play_next(ctx)
                except Exception:
                    pass
            elif isinstance(interaction_or_ctx, commands.Context):
                self.play_next(interaction_or_ctx)

    @commands.command(name='입장', aliases=['노래봇'])
    async def join(self, ctx: commands.Context):
        if not ctx.author.voice:
            return await ctx.send("❌ 음성 채널에 먼저 들어가주세요.")
        channel = ctx.author.voice.channel
        if ctx.voice_client:
            await ctx.voice_client.move_to(channel)
        else:
            await channel.connect()
        await ctx.send(f"✅ **{channel}** 채널에 연결되었습니다.")

    @commands.command(name='재생', aliases=['노래'])
    async def play(self, ctx: commands.Context, *, search: str):
        if not ctx.voice_client:
            await ctx.invoke(self.join)
            if not ctx.voice_client:
                return

        async with ctx.typing():
            self.queue.setdefault(ctx.guild.id, [])
            self.queue[ctx.guild.id].append({'original_search': search, 'title': search})

            if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
                await ctx.send(f"📂 대기열 추가: **{search}**")
            else:
                self.play_next(ctx)

    @commands.command(name='스킵', aliases=['다음', 'skip'])
    async def skip_cmd(self, ctx: commands.Context):
        gid = ctx.guild.id
        if ctx.voice_client and ctx.voice_client.is_playing():
            if self.repeat_mode.get(gid) == 'one':
                self.current_song.pop(gid, None)
            ctx.voice_client.stop()
            await ctx.send("⏭️ 현재 노래를 건너뜁니다.")
        else:
            await ctx.send("❌ 재생 중인 곡이 없습니다.")

    @commands.command(name='목록', aliases=['q', 'queue'])
    async def queue_list(self, ctx: commands.Context):
        gid = ctx.guild.id
        if not self.queue.get(gid):
            return await ctx.send("📭 현재 대기열이 비어있습니다.")

        songs = self.queue[gid]
        total = len(songs)
        vol = int(self._get_volume(gid) * 100)
        mode_text = {"none": "안 함", "one": "1곡", "all": "전체"}
        repeat_status = mode_text.get(self.repeat_mode.get(gid, 'none'), "안 함")
        played_count = len(self.played_songs.get(gid, []))
        played_text = f" | 순환 대기: {played_count}곡" if self.repeat_mode.get(gid) == 'all' and played_count > 0 else ""

        page_size = 10
        total_pages = max(1, math.ceil(total / page_size))
        pages = []
        for p in range(total_pages):
            chunk = songs[p * page_size:(p + 1) * page_size]
            embed = discord.Embed(title="🎶 현재 대기열", color=0x3498db)
            lines = "\n".join(f"{p * page_size + i + 1}. {s['title']}" for i, s in enumerate(chunk))
            embed.description = f"```\n{lines}\n```"
            footer = f"볼륨: {vol}% | 반복: {repeat_status}{played_text} | 총 {total}곡"
            if total_pages > 1:
                footer += f" | {p + 1}/{total_pages} 페이지"
            embed.set_footer(text=footer)
            pages.append(embed)

        view = PageView(pages, ctx.author.id) if total_pages > 1 else None
        await ctx.send(embed=pages[0], view=view)

    @commands.command(name='삭제', aliases=['제거', 'del', 'remove'])
    async def remove_song(self, ctx: commands.Context, index: int):
        gid = ctx.guild.id
        if not self.queue.get(gid):
            return await ctx.send("📭 대기열이 비어있습니다.")
        if index < 1:
            return await ctx.send("❌ 1 이상의 올바른 번호를 입력해주세요.")
        try:
            removed = self.queue[gid].pop(index - 1)
            await ctx.send(f"✅ 대기열에서 **{removed['title']}** 곡을 삭제했습니다.")
        except IndexError:
            await ctx.send("❌ 잘못된 번호입니다. `!목록`으로 번호를 확인하세요.")

    @commands.command(name='볼륨', aliases=['vol', 'v'])
    async def volume_cmd(self, ctx: commands.Context, vol: int):
        if vol < 0 or vol > 100:
            return await ctx.send("❌ 볼륨은 0~100 사이로 설정해주세요.")
        gid = ctx.guild.id
        self.volume[gid] = vol / 100
        if ctx.voice_client and ctx.voice_client.source:
            ctx.voice_client.source.volume = self.volume[gid]
        await ctx.send(f"🔊 볼륨을 **{vol}%**로 설정했습니다.")

    @commands.command(name='셔플', aliases=['섞기', 'shuffle'])
    async def shuffle_cmd(self, ctx: commands.Context):
        gid = ctx.guild.id
        if self.queue.get(gid) and len(self.queue[gid]) > 1:
            random.shuffle(self.queue[gid])
            await ctx.send(f"🔀 대기열 {len(self.queue[gid])}곡을 무작위로 섞었습니다!")
        else:
            await ctx.send("📭 섞을 곡이 부족합니다.")

    @commands.command(name='반복', aliases=['1곡반복', 'loop'])
    async def repeat_one(self, ctx: commands.Context):
        self.repeat_mode[ctx.guild.id] = 'one'
        await ctx.send("🔂 **1곡 반복** 모드를 활성화했습니다.")

    @commands.command(name='전체반복', aliases=['loopall'])
    async def repeat_all(self, ctx: commands.Context):
        self.repeat_mode[ctx.guild.id] = 'all'
        await ctx.send("🔁 **전체 반복** 모드를 활성화했습니다.")

    @commands.command(name='반복종료', aliases=['unloop'])
    async def repeat_off(self, ctx: commands.Context):
        self.repeat_mode[ctx.guild.id] = 'none'
        await ctx.send("❌ 반복 재생을 종료합니다.")

    @commands.command(name='나가기', aliases=['나가', 'ㅂㅂ', 'disconnect', 'leave'])
    async def leave(self, ctx: commands.Context):
        if ctx.voice_client:
            gid = ctx.guild.id
            prev_msg = self.now_playing_msg.pop(gid, None)
            task = self.alone_timers.pop(gid, None)
            if task:
                task.cancel()
            self.queue.pop(gid, None)
            self.repeat_mode.pop(gid, None)
            self.current_song.pop(gid, None)
            self.played_songs.pop(gid, None)
            self.dj_mode.pop(gid, None)
            await ctx.voice_client.disconnect()
            if prev_msg:
                try:
                    await prev_msg.delete()
                except Exception:
                    pass
            await ctx.send("⏹️ 음성 채널에서 퇴장했습니다.")
        else:
            await ctx.send("❌ 음성 채널에 연결되어 있지 않습니다.")

    @commands.command(name='자동', aliases=['자동재생', 'auto'])
    async def dj_mode_on(self, ctx: commands.Context):
        if not ctx.voice_client:
            return await ctx.send("❌ 먼저 음성 채널에 입장해주세요.")

        gid = ctx.guild.id
        self.dj_mode[gid] = True
        self.queue.setdefault(gid, [])

        msg = await ctx.send("🎵 **자동 모드** 활성화 중... 대기열을 10곡으로 채워드립니다.")
        try:
            needed = 10 - len(self.queue[gid])
            if needed > 0:
                recs = await self._get_recommended_songs(ctx.author.id, gid, '', needed)
                if recs:
                    for rec in recs:
                        self.queue[gid].append({'original_search': rec['url'], 'title': rec['title']})
                    await msg.edit(content=f"✅ **자동 모드** 활성화! 대기열에 **{len(recs)}곡** 추가됨.")
                    if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
                        self.play_next(ctx)
                else:
                    await msg.edit(content="🎵 **자동 모드** 활성화! (추천 곡 로드 실패)")
            else:
                await msg.edit(content="✅ **자동 모드** 활성화! 대기열이 이미 차 있습니다.")
                if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
                    self.play_next(ctx)
        except Exception as e:
            logger.error(f"[MusicCog] 자동 모드 초기화 오류: {e}")
            await msg.edit(content=f"⚠️ 초기화 중 오류: {str(e)[:100]}")

    @commands.command(name='자동끄기', aliases=['자동해제', 'autooff'])
    async def dj_mode_off(self, ctx: commands.Context):
        gid = ctx.guild.id
        self.dj_mode[gid] = False
        self.artist_count.pop(gid, None)
        self.last_recommended.pop(gid, None)
        await ctx.send("❌ **자동 모드**가 비활성화되었습니다.")

    @commands.command(name='추천', aliases=['추천곡', 'recommend'])
    async def recommend(self, ctx: commands.Context):
        if not ctx.voice_client:
            return await ctx.send("❌ 먼저 음성 채널에 입장해주세요.")

        gid = ctx.guild.id
        if not self.current_song.get(gid):
            return await ctx.send("❌ 현재 재생 중인 곡이 없습니다.")

        current_title = self.current_song[gid]['title']
        msg = await ctx.send("🔄 추천곡을 계산 중입니다...")
        try:
            recs = await self._get_recommended_songs(ctx.author.id, gid, current_title)
            if not recs:
                return await msg.edit(content="❌ 추천할 곡을 찾을 수 없습니다.")

            embed = discord.Embed(title="🎵 추천 곡", description=f"현재: **{current_title}** 기반", color=0xffa500)
            for idx, rec in enumerate(recs[:5], 1):
                embed.add_field(name=f"{idx}. {rec['title'][:50]}", value=f"[링크]({rec['url']})", inline=False)
            embed.set_footer(text=f"총 {len(recs)}곡 추천 | !자동 명령어로 자동 재생 가능")
            await msg.edit(content=None, embed=embed)
        except Exception as e:
            logger.error(f"[MusicCog] 추천 명령어 오류: {e}")
            await msg.edit(content=f"❌ 추천 중 오류: {str(e)[:100]}")

    @commands.command(name='상태', aliases=['status', 'info', '정보'])
    async def status(self, ctx: commands.Context):
        try:
            embed = discord.Embed(title="🤖 봇 상태 정보", color=0x00ff00, timestamp=ctx.message.created_at)
            embed.add_field(
                name="🎵 재생 상태",
                value=f"활성 음성 채널: **{len(self.bot.voice_clients)}**\n"
                      f"전체 대기열: **{sum(len(q) for q in self.queue.values())}**곡\n"
                      f"자동 모드 활성: **{sum(1 for v in self.dj_mode.values() if v)}**곳",
                inline=True
            )
            try:
                import psutil
                process = psutil.Process()
                embed.add_field(
                    name="💻 시스템",
                    value=f"메모리: **{process.memory_info().rss / 1024 / 1024:.1f}MB**\n"
                          f"CPU: **{process.cpu_percent(interval=0.1):.1f}%**\n"
                          f"서비스 길드: **{len(self.bot.guilds)}**곳",
                    inline=True
                )
            except ImportError:
                pass
            embed.add_field(
                name="📊 캐시",
                value=f"캐시된 길드: **{len(self.queue)}**곳\n"
                      f"추천 캐시: **{len(self.last_recommended)}**곳\n"
                      f"아티스트 캐시: **{len(self.artist_count)}**곳",
                inline=True
            )
            embed.set_footer(text=f"Discord.py {discord.__version__} • yt-dlp")
            await ctx.send(embed=embed)
        except Exception as e:
            logger.error(f"[MusicCog] 상태 명령어 오류: {e}")
            await ctx.send(f"❌ 상태 조회 실패: {str(e)[:100]}")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.id == self.bot.user.id:
            return

        vc = member.guild.voice_client
        if not vc:
            return

        gid = member.guild.id

        if after.channel and after.channel == vc.channel:
            task = self.alone_timers.pop(gid, None)
            if task:
                task.cancel()

        if before.channel and before.channel == vc.channel:
            if not any(not m.bot for m in vc.channel.members) and gid not in self.alone_timers:
                self.alone_timers[gid] = asyncio.create_task(self._alone_disconnect(member.guild))

    async def _alone_disconnect(self, guild: discord.Guild):
        await asyncio.sleep(180)
        gid = guild.id
        self.alone_timers.pop(gid, None)

        vc = guild.voice_client
        if not vc or not vc.is_connected():
            return
        if any(not m.bot for m in vc.channel.members):
            return

        prev_msg = self.now_playing_msg.pop(gid, None)
        if prev_msg:
            try:
                await prev_msg.delete()
            except Exception:
                pass

        self.queue.pop(gid, None)
        self.repeat_mode.pop(gid, None)
        self.current_song.pop(gid, None)
        self.played_songs.pop(gid, None)
        self.dj_mode.pop(gid, None)

        await vc.disconnect()
        logger.info(f"[{guild.name}] 채널에 혼자 남아 자동 퇴장.")


async def setup(bot):
    await bot.add_cog(MusicCog(bot))
