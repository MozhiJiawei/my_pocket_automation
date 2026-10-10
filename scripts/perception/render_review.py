"""Render existing proposals read-only; never generate or approve annotations."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.perception.lib.corpus import load_cases, image_path


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    workspace=ROOT/'.tmp/annotation/zhuagui'
    folder=(args.output or ROOT/'debug-runs'/datetime.now().strftime('%Y%m%d_%H%M%S')/'annotation-review').resolve()
    if not folder.is_relative_to((ROOT/'debug-runs').resolve()): parser.error('Review output must remain within debug-runs')
    folder.mkdir(parents=True,exist_ok=True)
    proposals=json.loads((workspace/'proposals.json').read_text(encoding='utf-8'))
    cases={c['id']:c for c in load_cases('zhuagui')}
    font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',20)
    sheet=Image.new('RGB',(960,((len(proposals)+3)//4)*235),'white')
    lines=['# AI 真值标注提案','',
           '整题审核请使用 [整轮审核工具](</D:/Agent Repo/my_pocket_automation/scripts/perception/README.md>)，本页仅保留单类物品识别参考，不能代表一项任务的完整答案集合。','',
           '高/中/低是主观把握，不是测得的正确率。绿色框已有独立验证，橙色框待审核。其他题目的干扰项可补充物品标注，不能抵扣缺失题目。','',
           '|编号|类别|把握|依据|标注图|','|---|---|---|---|---|']
    for i,p in enumerate(proposals):
        verified=p['status'] in {'verified','user_verified'}
        x=(i%4)*240; y=(i//4)*235
        draw=ImageDraw.Draw(sheet)
        draw.text((x+10,y+8),f"{i+1}. {p['topic']}  {p['confidence']}",font=font,fill='black')
        link='无可靠候选'
        if p['case_id']:
            frame=Image.open(image_path(cases[p['case_id']])).convert('RGB')
            sheet.paste(frame.crop(p['region']).resize((150,150)),(x+40,y+40))
            target=folder/f'{i+1:02d}.png'
            ImageDraw.Draw(frame).rectangle(p['region'],outline='green' if verified else 'orange',width=5)
            frame.save(target)
            link=f'[查看](</{target.as_posix()}>)'
        draw.text((x+10,y+202),'独立验证' if verified else '待审核',font=font,fill='green' if verified else 'darkorange')
        lines.append(f"|{i+1}|{p['topic']}|{p['confidence']}|{p['reason']}|{link}|")
    sheet.save(folder/'overview.png')
    (folder/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')

if __name__=='__main__': main()
