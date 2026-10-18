"""Rebuild the bundled bank from the seven source TXT blocks in this repository."""
import re,json,shutil
from pathlib import Path
root=Path(__file__).resolve().parents[2];out=root/'Detective_Portal/education_data'
(out/'images').mkdir(parents=True,exist_ok=True)
blocks=[('life','Безпека життєдіяльності','Pytannia_ta_vidpovidi_1-125.txt',125),('medical','Домедична допомога · II','Domedychna_dopomoha_II_1-655.txt',655),('force','Поліцейські заходи примусу · III','Politsiiski_zakhody_prymusu_III_1-193.txt',193),('weapons','Матеріальна частина зброї · IV','Materialna_chastyna_zbroi_IV/pytannia_1-458.txt',458),('safety','Безпека зі зброєю · V','Zakhody_bezpeky_zi_zbroieiu_V_1-300.txt',300),('tactics','Тактична підготовка · VI','Taktychna_pidhotovka_VI_1-345.txt',345),('psychology','Психологічна підготовка · LX','Psykholohichna_pidhotovka_LX_1-226.txt',226)]
records=[];metadata=[]
for bid,label,file,count in blocks:
 text=(root/file).read_text(encoding='utf-8-sig')
 matches=list(re.finditer(r'^(\d+)\. (.*?)\nВідповідь: (.*?)(?=\n\n\d+\. |\Z)',text,re.S|re.M))
 assert len(matches)==count,(bid,len(matches))
 for m in matches:
  n=int(m[1]);q=m[2].strip();image=None
  photo=re.search(r'\nЗображення: (.+)',q)
  if photo:
   image=photo[1].strip();q=q[:photo.start()].strip()
   shutil.copyfile(root/'Materialna_chastyna_zbroi_IV'/image,out/image)
  answer=m[3].strip()
  # Keep existing parenthetical explanations; make plain source answers available
  # to the same parentheses-only variant list without changing their wording.
  if '(' not in answer or ')' not in answer:
   answer=f'({answer})'
  records.append(dict(id=f'{bid}:{n}',block=bid,number=n,question=q,answer=answer,image=image))
 metadata.append(dict(id=bid,title=label,count=count))
(out/'questions.json').write_text(json.dumps(dict(version=1,blocks=metadata,questions=records),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('Imported',len(records),'questions',sum(bool(r['image']) for r in records),'images')
