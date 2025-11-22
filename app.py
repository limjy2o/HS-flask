#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""單字測驗系統 Flask 版本"""
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.utils import secure_filename
import os
import json
import random
import time
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict
from enum import Enum

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this-in-production'
app.config['UPLOAD_FOLDER'] = 'vocab_data'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['JSON_AS_ASCII'] = False  # 確保 JSON 正確處理中文
app.config['SESSION_TYPE'] = 'filesystem'  # 使用檔案系統儲存 session
app.config['PERMANENT_SESSION_LIFETIME'] = 3600  # Session 有效期 1 小時

# 確保資料夾存在
Path(app.config['UPLOAD_FOLDER']).mkdir(exist_ok=True)

class TestMode(Enum):
    MODE_A = "A"
    MODE_B = "B"
    MODE_C = "C"

@dataclass
class VocabQuestion:
    word: str
    pos: str
    meaning: str
    
    def __post_init__(self):
        self.word = self.word.strip()
        self.pos = self.pos.strip()
        self.meaning = self.meaning.strip()
    
    @property
    def pos_list(self) -> List[str]:
        return [p.strip() for p in self.pos.split('&')]
    
    @property
    def meaning_list(self) -> List[str]:
        return [m.strip() for m in self.meaning.split('&')]
    
    def check_answer_mode_a(self, user_pos_list: List[str], user_meaning_list: List[str]) -> bool:
        user_pos_clean = {p.strip() for p in user_pos_list if p.strip()}
        user_meaning_clean = {m.strip() for m in user_meaning_list if m.strip()}
        correct_pos = set(self.pos_list)
        correct_meaning = set(self.meaning_list)
        return user_pos_clean == correct_pos and user_meaning_clean == correct_meaning
    
    def check_answer_mode_b(self, user_word: str) -> bool:
        return user_word.strip().lower() == self.word.lower()
    
    def to_dict(self):
        return {
            'word': self.word,
            'pos': self.pos,
            'meaning': self.meaning
        }

class QuestionBank:
    def __init__(self, name: str, questions: List[VocabQuestion] = None):
        self.name = name
        self.questions = questions if questions is not None else []
    
    def load_from_file(self, filepath) -> bool:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            self.questions.clear()
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                parts = line.split('\t')
                if len(parts) >= 3:
                    self.questions.append(VocabQuestion(parts[0], parts[1], parts[2]))
            return len(self.questions) > 0
        except Exception as e:
            print(f"Error loading file: {e}")
            return False
    
    def __len__(self) -> int:
        return len(self.questions)

def load_banks():
    """載入所有題庫"""
    banks_file = Path(app.config['UPLOAD_FOLDER']) / 'banks.json'
    question_banks = {}
    if banks_file.exists():
        try:
            with open(banks_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for bank_name, questions_data in data.items():
                bank = QuestionBank(bank_name)
                for q_data in questions_data:
                    question = VocabQuestion(q_data['word'], q_data['pos'], q_data['meaning'])
                    bank.questions.append(question)
                question_banks[bank_name] = bank
        except Exception as e:
            print(f"Error loading banks: {e}")
    return question_banks

def save_banks(question_banks):
    """儲存所有題庫"""
    banks_file = Path(app.config['UPLOAD_FOLDER']) / 'banks.json'
    try:
        data = {
            name: [q.to_dict() for q in bank.questions]
            for name, bank in question_banks.items()
        }
        with open(banks_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"Error saving banks: {e}")
        return False

@app.route('/')
def index():
    """主頁面"""
    question_banks = load_banks()
    return render_template('index.html', banks=question_banks)

@app.route('/upload', methods=['POST'])
def upload_bank():
    """上傳題庫檔案"""
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': '沒有選擇檔案'})
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'message': '沒有選擇檔案'})
    
    if file:
        # 使用原始檔名而不是 secure_filename 來保留中文
        original_filename = file.filename
        bank_name = Path(original_filename).stem
        
        # 創建安全的儲存路徑
        timestamp = int(time.time() * 1000)
        safe_filename = f"temp_{timestamp}.txt"
        filepath = Path(app.config['UPLOAD_FOLDER']) / safe_filename
        
        file.save(str(filepath))
        
        # 載入題庫
        question_banks = load_banks()
        bank = QuestionBank(bank_name)
        
        if bank.load_from_file(filepath):
            question_banks[bank_name] = bank
            save_banks(question_banks)
            # 刪除暫存檔案
            filepath.unlink()
            return jsonify({
                'success': True,
                'message': f'題庫 {bank_name} 載入成功,共 {len(bank)} 題'
            })
        else:
            filepath.unlink()
            return jsonify({'success': False, 'message': '題庫檔案格式錯誤'})

@app.route('/delete_bank/<bank_name>', methods=['POST'])
def delete_bank(bank_name):
    """刪除題庫"""
    question_banks = load_banks()
    if bank_name in question_banks:
        del question_banks[bank_name]
        save_banks(question_banks)
        return jsonify({'success': True, 'message': f'題庫 {bank_name} 已刪除'})
    return jsonify({'success': False, 'message': '題庫不存在'})

@app.route('/start_quiz', methods=['POST'])
def start_quiz():
    """開始測驗"""
    data = request.json
    selected_banks = data.get('selected_banks', [])
    count_mode = data.get('count_mode', '0.75')
    custom_count = data.get('custom_count', 100)
    test_mode = data.get('test_mode', 'A')
    
    if not selected_banks:
        return jsonify({'success': False, 'message': '請至少選擇一個題庫'})
    
    # 準備題目
    question_banks = load_banks()
    all_questions = []
    for bank_name in selected_banks:
        if bank_name in question_banks:
            all_questions.extend(question_banks[bank_name].questions)
    
    if not all_questions:
        return jsonify({'success': False, 'message': '沒有可用的題目'})
    
    # 計算題數
    total_available = len(all_questions)
    if count_mode == 'custom':
        try:
            # 自訂題數：可以選擇任意數量,只要不超過總題數
            target_count = min(int(custom_count), total_available)
            if target_count < 1:
                target_count = 1
        except:
            target_count = total_available
    else:
        # 比例模式：根據比例計算題數
        ratio = float(count_mode)
        target_count = max(1, round(total_available * ratio))
        # 確保不超過總題數
        target_count = min(target_count, total_available)
    
    # 隨機選題
    selected_questions = random.sample(all_questions, min(target_count, total_available))
    random.shuffle(selected_questions)
    
    # 設定題目模式
    question_modes = []
    for _ in selected_questions:
        if test_mode == 'C':
            question_modes.append(random.choice(['A', 'B']))
        else:
            question_modes.append(test_mode)
    
    # 儲存到 session
    session['questions'] = [q.to_dict() for q in selected_questions]
    session['question_modes'] = question_modes
    session['test_mode'] = test_mode
    session['start_time'] = time.time()
    
    return jsonify({'success': True, 'redirect': url_for('quiz')})

@app.route('/quiz')
def quiz():
    """測驗頁面"""
    if 'questions' not in session:
        return redirect(url_for('index'))
    
    questions = session['questions']
    question_modes = session['question_modes']
    test_mode = session['test_mode']
    
    mode_names = {
        'A': '中文解釋及詞性測驗',
        'B': '拼字測驗',
        'C': '混合模式'
    }
    
    return render_template('quiz.html',
                         questions=questions,
                         question_modes=question_modes,
                         test_mode=test_mode,
                         mode_name=mode_names[test_mode])

@app.route('/submit_answers', methods=['POST'])
def submit_answers():
    """提交答案並批改"""
    try:
        if 'questions' not in session:
            return jsonify({'success': False, 'message': '測驗已過期,請重新開始'})
        
        data = request.json
        user_answers = data.get('answers', [])
        
        questions_data = session.get('questions', [])
        question_modes = session.get('question_modes', [])
        start_time = session.get('start_time', time.time())
        
        if not questions_data or not question_modes:
            return jsonify({'success': False, 'message': '測驗資料遺失,請重新開始'})
        
        # 重建 VocabQuestion 物件
        questions = [VocabQuestion(q['word'], q['pos'], q['meaning']) for q in questions_data]
        
        # 批改答案
        results = []
        correct_count = 0
        
        for i, (question, mode) in enumerate(zip(questions, question_modes)):
            user_answer = user_answers[i] if i < len(user_answers) else {}
            
            if mode == 'A':
                user_pos_list = user_answer.get('pos', [])
                user_meaning_list = user_answer.get('meaning', [])
                is_correct = question.check_answer_mode_a(user_pos_list, user_meaning_list)
                results.append({
                    'mode': 'A',
                    'question': question.to_dict(),
                    'user_pos_list': user_pos_list,
                    'user_meaning_list': user_meaning_list,
                    'correct': is_correct
                })
            else:  # mode == 'B'
                user_word = user_answer.get('word', '')
                is_correct = question.check_answer_mode_b(user_word)
                results.append({
                    'mode': 'B',
                    'question': question.to_dict(),
                    'user_word': user_word,
                    'correct': is_correct
                })
            
            if is_correct:
                correct_count += 1
        
        end_time = time.time()
        total_time = int(end_time - start_time)
        
        # 儲存結果到 session
        session['results'] = results
        session['correct_count'] = correct_count
        session['total_time'] = total_time
        session.modified = True  # 確保 session 被標記為已修改
        
        print(f"Results saved to session: {len(results)} questions, {correct_count} correct")  # Debug log
        
        return jsonify({'success': True, 'redirect': url_for('result')})
        
    except Exception as e:
        print(f"Error in submit_answers: {e}")  # Debug log
        return jsonify({'success': False, 'message': f'提交失敗: {str(e)}'})

@app.route('/result')
def result():
    """結果頁面"""
    if 'results' not in session:
        return redirect(url_for('index'))
    
    results = session['results']
    correct_count = session['correct_count']
    total_time = session['total_time']
    total_questions = len(results)
    accuracy = (correct_count / total_questions * 100) if total_questions > 0 else 0
    
    return render_template('result.html',
                         results=results,
                         correct_count=correct_count,
                         total_questions=total_questions,
                         accuracy=accuracy,
                         total_time=total_time)

@app.route('/get_bank_count', methods=['POST'])
def get_bank_count():
    """取得選中題庫的總題數"""
    data = request.json
    selected_banks = data.get('selected_banks', [])
    
    question_banks = load_banks()
    total = sum(len(question_banks[name]) for name in selected_banks if name in question_banks)
    
    return jsonify({'total': total})

import os

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
