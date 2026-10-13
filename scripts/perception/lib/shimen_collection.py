"""Track collected categories, never infer correct answers."""
import itertools
import re
import cv2
import numpy as np

def question(words):
    text=next((w['text'] for w in words if '请找到' in w['text']),None)
    if not text:return None
    match=re.search(r'请找到(.+?)[Xx×](\d+)',text)
    return (match[1],int(match[2])) if match else None

def saturated(rounds,new_material):
    if rounds!=10 or new_material<0:raise ValueError('A complete ten-round batch is required')
    return new_material==0

class Novelty:
    def __init__(self):self.questions=set();self.puzzles=[]
    def items(self,topic):
        added=int(topic not in self.questions)
        self.questions.add(topic)
        return added
    def puzzle(self,parts):
        samples=[cv2.resize(p,(24,30)).astype(np.float32) for p in parts]
        for index,previous in enumerate(self.puzzles,1):
            costs=np.array([[np.abs(a-b).mean() for b in previous] for a in samples])
            if min(sum(costs[i,j] for i,j in enumerate(p))/4 for p in itertools.permutations(range(4)))<6:
                self.last_family=index;return 0
        self.puzzles.append(samples);self.last_family=len(self.puzzles);return 1
