import streamlit as st
import json
import os
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from functools import lru_cache

from utils import load_question_files, grade_to_value

# Constants
GRADE_MAPPING = {'A': 0, 'B': 1, 'C': 2, 'D': 3, 'E': 4, 'F': 5, 'G': 6}
LETTER_MAPPING = ['A', 'B', 'C', 'D', 'E', 'F', 'G']

@dataclass
class ScoreData:
    """Centralized score data structure"""
    indicator_scores: Dict[str, int]
    criterion_scores: Dict[str, float]
    value_scores: Dict[str, float]

class QuestionnaireProcessor:
    """Handles all questionnaire data processing and calculations"""
    
    def __init__(self, question_files: Dict):
        self.question_files = question_files
        self._score_cache = None
    
    @staticmethod
    def option_id_to_grade(option_id: str) -> int:
        """Convert option ID to numerical grade"""
        return GRADE_MAPPING.get(option_id.upper(), 0)
    
    @staticmethod
    def grade_to_letter(grade: float) -> str:
        """Convert numerical grade to letter"""
        if 0 <= grade <= 6:
            return LETTER_MAPPING[int(round(grade))]
        return 'A'
    
    def calculate_all_scores(self, answers: Dict) -> ScoreData:
        """Calculate all scores efficiently in one pass"""
        if not answers:
            return ScoreData({}, {}, {})
        
        # Calculate indicator scores
        indicator_scores = self._calculate_indicator_scores(answers)
        
        # Calculate criterion scores (collections within questionnaires)
        criterion_scores = self._calculate_criterion_scores(indicator_scores)
        
        # Calculate value scores (questionnaires)
        value_scores = self._calculate_value_scores(criterion_scores)

        # add caching for performance
        self._score_cache = (indicator_scores, criterion_scores, value_scores)

        
        return ScoreData(indicator_scores, criterion_scores, value_scores)
    
    def _calculate_indicator_scores(self, answers: Dict) -> Dict[str, int]:
        """Calculate scores for each indicator (question)"""
        indicator_scores = {}
        
        for answer_key, answer_data in answers.items():
            parts = answer_key.split('_')
            if len(parts) < 3:
                continue
                
            page_key, collection_id, question_index = parts[0], parts[1], int(parts[2])
            
            # Find the question to get its ID
            if page_key in self.question_files:
                collections = self.question_files[page_key]['question_collections']
                for collection in collections:
                    if collection['collection_id'] == collection_id:
                        if question_index < len(collection['questions']):
                            question = collection['questions'][question_index]
                            question_id = question.get('question_id', f"{collection_id}_{question_index}")
                            grade = self.option_id_to_grade(answer_data['option_id'])
                            indicator_scores[question_id] = grade
                            break
        
        return indicator_scores
    
    def _calculate_criterion_scores(self, indicator_scores: Dict[str, int]) -> Dict[str, float]:
        """Calculate criterion scores (average of indicators within each collection)"""
        criterion_scores = {}
        
        for page_key, page_data in self.question_files.items():
            collections = page_data.get('question_collections', [])
            
            for collection in collections:
                collection_id = collection['collection_id']
                questions = collection.get('questions', [])
                
                # Get scores for all questions in this collection
                scores = []
                for question in questions:
                    question_id = question.get('question_id')
                    if question_id and question_id in indicator_scores:
                        scores.append(indicator_scores[question_id])
                
                if scores:
                    criterion_scores[collection_id] = sum(scores) / len(scores)
        
        return criterion_scores
    
    def _calculate_value_scores(self, criterion_scores: Dict[str, float]) -> Dict[str, float]:
        """Calculate value scores (average of criteria within each questionnaire)"""
        value_scores = {}
        
        for page_key, page_data in self.question_files.items():
            value_name = page_data.get('questionnaire_info', {}).get('title', page_key)
            collections = page_data.get('question_collections', [])
            
            # Get scores for all collections in this questionnaire
            scores = []
            for collection in collections:
                collection_id = collection['collection_id']
                if collection_id in criterion_scores:
                    scores.append(criterion_scores[collection_id])
            
            if scores:
                value_scores[value_name] = sum(scores) / len(scores)
        
        return value_scores
    
    def get_progress_data(self, answers: Dict) -> Dict:
        """Calculate progress statistics for all questionnaires"""
        progress_data = {}
        total_all = answered_all = 0
        
        for page_name, page_data in self.question_files.items():
            total_questions = answered_questions = 0
            
            for collection in page_data['question_collections']:
                collection_id = collection['collection_id']
                collection_total = len(collection['questions'])
                collection_answered = len([k for k in answers.keys() 
                                         if k.startswith(f"{page_name}_{collection_id}")])
                
                total_questions += collection_total
                answered_questions += collection_answered
            
            total_all += total_questions
            answered_all += answered_questions
            
            progress_data[page_name] = {
                'total': total_questions,
                'answered': answered_questions,
                'progress': answered_questions / total_questions if total_questions > 0 else 0
            }
        
        progress_data['overall'] = {
            'total': total_all,
            'answered': answered_all,
            'progress': answered_all / total_all if total_all > 0 else 0
        }
        
        return progress_data

def initialize_session_state():
    """Initialize session state variables"""
    defaults = {
        'current_question': {},
        'answers': {},
        'current_page': None
    }
    
    for key, default_value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value

def display_question(question: Dict, question_key: int, page_key: str, collection_id: str):
    """Display a single question with answer options"""
    st.markdown(f"### {question['question_text']}")
    st.caption(f"Question ID: {question['question_id']}")
    
    if question.get('subquestion'):
        st.caption(question['subquestion'])
    
    if question.get('guidance'):
        st.markdown(f"*{question['guidance']}*")
    
    answer_options = question.get('answer_options', [])
    if not answer_options:
        st.warning("No answer options available for this question.")
        return
    
    # Create display options
    display_options = []
    option_mapping = {}
    
    for option in answer_options:
        if option['option_text'].strip():
            display_text = f"({option['option_id']}) -- {option['option_text']}"
            display_options.append(display_text)
            option_mapping[display_text] = option
    
    if not display_options:
        st.warning("No valid answer options available for this question.")
        return
    
    # Create unique key and handle selection
    unique_key = f"{page_key}_{collection_id}_{question_key}_answer"
    selected_answer = st.radio("Select your answer:", display_options, key=unique_key, index=None)
    
    # Store answer
    answer_storage_key = f"{page_key}_{collection_id}_{question_key}"
    if selected_answer:
        st.session_state.answers[answer_storage_key] = option_mapping[selected_answer]
        
        # Display follow-up questions
        followup_questions = question.get('followup_questions', [])
        if followup_questions:
            st.write("**Follow-up questions:**")
            for followup in followup_questions:
                st.write(f"- {followup}")

def display_collection(collection: Dict, page_key: str):
    """Display all questions in a collection with navigation"""
    st.header(f"{collection['collection_id']} - {collection['collection_title']}")
    st.write(collection['collection_description'])
    
    collection_id = collection['collection_id']
    questions = collection['questions']
    total_questions = len(questions)
    
    if total_questions == 0:
        st.warning("No questions found in this collection.")
        return
    
    # Initialize current question index
    collection_key = f"{page_key}_{collection_id}"
    if collection_key not in st.session_state.current_question:
        st.session_state.current_question[collection_key] = 0
    
    current_q_index = st.session_state.current_question[collection_key]
    
    # Display progress and current question
    st.progress((current_q_index + 1) / total_questions)
    st.write(f"Question {current_q_index + 1} of {total_questions}")
    
    display_question(questions[current_q_index], current_q_index, page_key, collection_id)
    
    # Navigation buttons
    col1, col2, col3 = st.columns([1, 1, 1])
    
    with col1:
        if current_q_index > 0 and st.button("← Previous", key=f"{collection_key}_prev"):
            st.session_state.current_question[collection_key] -= 1
            st.rerun()
    
    with col2:
        st.write(f"Question {current_q_index + 1}")
    
    with col3:
        if current_q_index < total_questions - 1 and st.button("Next →", key=f"{collection_key}_next"):
            st.session_state.current_question[collection_key] += 1
            st.rerun()
        
        if st.button("💾 Save Answers", key=f"{collection_key}_save", type="primary"):
            collection_answers = [k for k in st.session_state.answers.keys() 
                                if k.startswith(f"{page_key}_{collection_id}")]
            if not collection_answers:
                st.warning("No answers recorded for this collection yet.")
                return
            # Save answers to session state
            st.success(f"Answers saved!")

def display_score_section(title: str, scores: Dict, emoji: str):
    """Display a section of scores in a consistent format"""
    if not scores:
        return
        
    st.subheader(f"{emoji} {title}")
    processor = QuestionnaireProcessor({})  # Empty init for static method access
    
    for name, score in scores.items():
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            st.write(f"**{name}**")
        with col2:
            if isinstance(score, float):
                st.write(f"Score: {score:.2f}")
            else:
                st.write(f"Score: {score}")
        with col3:
            st.write(f"Grade: {processor.grade_to_letter(score)}")
    
    st.write("---")

def summary_page():
    """Summary page displaying all results and statistics"""
    st.title("VDE Spec 90012 Evaluation App")
    st.header("📊 Aggregation Results")
    
    if not st.session_state.answers:
        st.info("No answers recorded yet. Please complete some questionnaires first.")
        return
    
    # Initialize processor and calculate scores
    question_files = load_question_files()
    processor = QuestionnaireProcessor(question_files)
    score_data = processor.calculate_all_scores(st.session_state.answers)
    overall_score = sum(score_data.value_scores.values())/len(score_data.value_scores) if score_data.value_scores else 0
    
    # Display results
    st.subheader(f"🏁 Overall Grade: {processor.grade_to_letter(overall_score)} (Score: {overall_score:.2f})")
    display_score_section("Value Scores", score_data.value_scores, "🎯")
    display_score_section("Criterion Scores", score_data.criterion_scores, "🔍")
    display_score_section("Indicator Scores", score_data.indicator_scores, "📋")
    
    # Detailed answers section
    st.header("📝 Detailed Answers")
    with st.expander("View All Individual Answers", expanded=False):
        for key, answer in st.session_state.answers.items():
            parts = key.split('_')
            if len(parts) >= 3:
                page_key, collection_id, question_index = parts[0], parts[1], parts[2]
                
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.write(f"**{page_key} - {collection_id} - Question {int(question_index) + 1}:**")
                    st.write(f"{answer['option_text']}")
                with col2:
                    grade = processor.option_id_to_grade(answer['option_id'])
                    st.write(f"Grade: {answer['option_id']} ({grade})")
                st.write("---")
    
    # Export section
    _display_export_section(score_data, processor)

    # Display progress overview and reset functionality in the sidebar
    with st.sidebar:
        _display_progress_section(processor)
        _display_reset_section()


def _display_export_section(score_data: ScoreData, processor: QuestionnaireProcessor):
    """Display export functionality"""
    st.header("💾 Export Results")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("📋 Copy Results to Clipboard"):
            results_text = "VDE Spec 90012 Evaluation Results\n\n"
            
            for section_name, scores in [
                ("Value Scores", score_data.value_scores),
                ("Criterion Scores", score_data.criterion_scores),
                ("Indicator Scores", score_data.indicator_scores)
            ]:
                if scores:
                    results_text += f"{section_name}:\n"
                    for name, score in scores.items():
                        if isinstance(score, float):
                            results_text += f"- {name}: {score:.2f} (Grade: {processor.grade_to_letter(score)})\n"
                        else:
                            results_text += f"- {name}: {score} (Grade: {processor.grade_to_letter(score)})\n"
                    results_text += "\n"
            
            st.code(results_text, language=None)
            st.success("Results formatted for copying!")
    
    with col2:
        if st.button("🔄 Recalculate Scores"):
            st.rerun()

def _display_progress_section(processor: QuestionnaireProcessor):
    """Display progress overview"""
    st.header("📈 Progress Overview")
    
    progress_data = processor.get_progress_data(st.session_state.answers)
    
    for page_name, stats in progress_data.items():
        if page_name == 'overall':
            continue
            
        col1, col2 = st.columns([3, 1])
        with col1:
            st.progress(stats['progress'])
        with col2:
            st.write(f"{page_name}: {stats['answered']}/{stats['total']}")
    
    # Overall progress
    overall = progress_data['overall']
    st.write("### Overall Progress")
    col1, col2 = st.columns([3, 1])
    with col1:
        st.progress(overall['progress'])
    with col2:
        st.write(f"Total: {overall['answered']}/{overall['total']}")

def _display_reset_section():
    """Display reset functionality"""
    st.header("🔄 Reset Data")
    if st.button("Reset All Answers", type="secondary"):
        if st.button("⚠️ Confirm Reset", type="primary"):
            st.session_state.answers = {}
            st.session_state.current_question = {}
            st.rerun()

def create_questionnaire_page_function(page_key: str, data: Dict):
    """Create a unique questionnaire page function"""
    def questionnaire_page_func():
        # Display questionnaire header
        title = data.get('questionnaire_info', {}).get('title', page_key)
        st.title(title)
        
        if data.get('questionnaire_info', {}).get('description'):
            st.write(f"**Description:** {data['questionnaire_info']['description']}")
        
        # Display version and creation info
        questionnaire_info = data.get('questionnaire_info', {})
        info_parts = []
        if questionnaire_info.get('version'):
            info_parts.append(f"Version: {questionnaire_info['version']}")
        if questionnaire_info.get('created_date'):
            info_parts.append(f"Created: {questionnaire_info['created_date']}")
        if info_parts:
            st.caption(" | ".join(info_parts))
        
        # Display collections
        for collection in data['question_collections']:
            display_collection(collection, page_key)
            st.write("---")

        # Add progress overview and reset functionality in the sidebar
        processor = QuestionnaireProcessor(load_question_files())
        with st.sidebar:
            _display_progress_section(processor)
            _display_reset_section()
    
    # Give the function a unique name for Streamlit
    questionnaire_page_func.__name__ = f"questionnaire_page_{page_key}"
    return questionnaire_page_func

def main():
    st.set_page_config(
        page_title="VDE Spec 90012 Evaluation App",
        page_icon="⏳",
        layout="wide"
    )
    
    initialize_session_state()
    
    question_files = load_question_files()
    if not question_files:
        st.warning("No question files found. Please add JSON files to the 'questions' folder.")
        return
    
    # Create pages
    pages = [st.Page(summary_page, title="Summary", icon="📊")]
    
    # Add questionnaire pages with unique identifiers
    for page_key, data in question_files.items():
        title = data.get('questionnaire_info', {}).get('title', page_key)
        page_func = create_questionnaire_page_function(page_key, data)
        pages.append(st.Page(page_func, title=title, icon="📝", url_path=f"questionnaire_{page_key}"))
    
    # Run navigation
    pg = st.navigation(pages)
    pg.run()


if __name__ == "__main__":
    main()