import re
import time
from collections import defaultdict

import hoshino
from hoshino import Service
from hoshino.typing import *
from hoshino.util import FreqLimiter, concat_pic, pic2b64
from PIL import Image, ImageSequence, ImageDraw, ImageFont

from .. import chara
from . import data

sv_help = '''
[怎么拆] 接防守队角色名 查询竞技场解法
[点赞] 接作业id 评价作业
[点踩] 接作业id 评价作业
'''.strip()
sv = Service('pcr-arena', help_=sv_help, bundle='pcr查询')

from . import arena

lmt = FreqLimiter(5)

aliases = ('怎么拆', '怎么解', '怎么打', '如何拆', '如何解', '如何打',
           '怎麼拆', '怎麼解', '怎麼打', 'jjc查询', 'jjc查詢')
aliases_b = tuple('b' + a for a in aliases) + tuple('B' + a for a in aliases)
aliases_tw = tuple('台' + a for a in aliases)
aliases_jp = tuple('日' + a for a in aliases)


@sv.on_prefix(aliases)
async def arena_query(bot, ev):
    await _arena_query(bot, ev, region=1)


@sv.on_prefix(aliases_b)
async def arena_query_b(bot, ev):
    await _arena_query(bot, ev, region=2)


@sv.on_prefix(aliases_tw)
async def arena_query_tw(bot, ev):
    await _arena_query(bot, ev, region=3)


@sv.on_prefix(aliases_jp)
async def arena_query_jp(bot, ev):
    await _arena_query(bot, ev, region=4)


async def _arena_query(bot, ev: CQEvent, region: int):

    arena.refresh_quick_key_dic()
    uid = ev.user_id

    if not lmt.check(uid):
        await bot.finish(ev, '您查询得过于频繁，请稍等片刻', at_sender=True)
    lmt.start_cd(uid)

    # 处理输入数据
    defen = ev.message.extract_plain_text()
    defen = re.sub(r'[?？，,_]', '', defen)
    defen, unknown = chara.roster.parse_team(defen)

    if unknown:
        _, name, score = chara.guess_id(unknown)
        if score < 70 and not defen:
            return  # 忽略无关对话
        msg = f'无法识别"{unknown}"' if score < 70 else f'无法识别"{unknown}" 您说的有{score}%可能是{name}'
        await bot.finish(ev, msg)
    if not defen:
        await bot.finish(ev, '查询请发送"怎么拆+防守队伍"，无需+号', at_sender=True)
    if len(defen) > 5:
        await bot.finish(ev, '编队不能多于5名角色', at_sender=True)
    if len(defen) < 5:
        await bot.finish(ev, '编队不能少于5名角色', at_sender=True)
    if len(defen) != len(set(defen)):
        await bot.finish(ev, '编队中含重复角色', at_sender=True)
    if any(chara.is_npc(i) for i in defen):
        await bot.finish(ev, '编队中含未实装角色', at_sender=True)
    if 1004 in defen:
        await bot.send(ev, '\n⚠️您正在查询普通版炸弹人\n※万圣版可用万圣炸弹人/瓜炸等别称', at_sender=True)

    defen.sort()

    # 执行查询
    # sv.logger.info('Doing query...')
    res = await arena.do_query(defen, uid, region)
    # sv.logger.info('Got response!')

    # 处理查询结果
    if isinstance(res, str):
        await bot.finish(ev, f'查询出错，{res}', at_sender=True)
    if not len(res):
        await bot.finish(ev, '抱歉没有查询到解法\n※没有作业说明随便拆 发挥你的想象力～★\n作业上传请前往pcrdfans.com', at_sender=True)
    res = res[:min(6, len(res))]    # 限制显示数量，截断结果

    atk_team = []
    absPath = "/root/HoshinoBot/hoshino/modules/priconne/arena"  # 这里是该hoshino模组的绝对路径
    font_path = f'{absPath}/font/seguiemj.ttf'
    for v in res:
        atk = v['atk']
        team_pic = chara.gen_team_pic(atk)
        up = v['up'] + v['my_up']
        down = v['down'] + v['my_down']
        qkey = v['qkey']
        pingjia = f'{qkey}\n\U0001F44D{up}\n\U0001F44E{down}'
        target = Image.new('RGBA', (64*6, 64), (255, 255, 255, 255))
        draw = ImageDraw.Draw(target)
        ttffont = ImageFont.truetype(font_path, 18)
        draw.text((64*5, 0), pingjia, font=ttffont, fill='#000000')
        target.paste(team_pic, (0, 0))
        atk_team.append(target)
    atk_team = concat_pic(atk_team)
    atk_team = pic2b64(atk_team)
    atk_team = str(MessageSegment.image(atk_team))

    defen = [chara.fromid(x).name for x in defen]
    defen = f"防守方【{' '.join(defen)}】"
    at = str(MessageSegment.at(ev.user_id))

    msg = [
        defen,
        f'已为骑士{at}查询到以下进攻方案：',
        str(atk_team),
        '※发送"点赞/点踩"可进行评价'
    ]
    if region == 1:
        msg.append('※使用"b怎么拆"或"台怎么拆"可按服过滤')
    msg.append('Support by pcrdfans_com')

    # sv.logger.debug('Arena sending result...')
    await bot.send(ev, '\n'.join(msg))
    # sv.logger.debug('Arena result sent!')


@sv.on_prefix('点赞')
async def arena_like(bot, ev):
    await _arena_feedback(bot, ev, 1)


@sv.on_prefix('点踩')
async def arena_dislike(bot, ev):
    await _arena_feedback(bot, ev, -1)


rex_qkey = re.compile(r'^[0-9a-zA-Z]{5}$')


async def _arena_feedback(bot, ev: CQEvent, action: int):
    action_tip = '赞' if action > 0 else '踩'
    qkey = ev.message.extract_plain_text().strip()
    if not qkey:
        await bot.finish(ev, f'请发送"点{action_tip}+作业id"，如"点{action_tip}ABCDE"，不分大小写', at_sender=True)
    if not rex_qkey.match(qkey):
        await bot.finish(ev, f'您要点{action_tip}的作业id不合法', at_sender=True)
    try:
        await arena.do_like(qkey, ev.user_id, action)
    except KeyError:
        await bot.finish(ev, '无法找到作业id！您只能评价您最近查询过的作业', at_sender=True)
    await bot.send(ev, '感谢您的反馈！', at_sender=True)


def get_atk_id(chara_list):
    res = ''
    for v in chara_list:
        res += f'{v.id},'
    res_len = len(res) - 1
    res = res[0:res_len]
    return res


@sv.on_fullmatch('查询jjc错误码')
async def query_error_code(bot, event):
    code = data.ERROR_CODE
    res = ''
    for index in code:
        res += f'{index}:{code[index]}\n'
    res = res.strip()
    msg = f'''
常见错误码如下：
{res}
'''.strip()
    await bot.send(event, msg)
