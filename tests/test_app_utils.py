import unittest
import os
import shutil
from app import parse_single_question_block, parse_markdown_questions, get_question_file_path

class TestMarkdownParsing(unittest.TestCase):

    def test_valid_question_block_all_fields(self):
        md_block = """
# Question 1
This is the question text?
- [ ] Option A
- [x] Option B (Correct)
- [ ] Option C
- [ ] Option D
Explanation: This is the explanation.
        """
        expected = {
            'text': 'This is the question text?',
            'option_a': 'Option A',
            'option_b': 'Option B (Correct)',
            'option_c': 'Option C',
            'option_d': 'Option D',
            'correct_option': 'B',
            'explanation': 'This is the explanation.'
        }
        # The actual parsing might produce HTML entities or minor differences, adjust as needed.
        # For now, this is a direct string comparison.
        result = parse_single_question_block(md_block)
        self.assertEqual(result['text'], expected['text'])
        self.assertEqual(result['option_a'], expected['option_a'])
        self.assertEqual(result['option_b'], expected['option_b'])
        self.assertEqual(result['option_c'], expected['option_c'])
        self.assertEqual(result['option_d'], expected['option_d'])
        self.assertEqual(result['correct_option'], expected['correct_option'])
        self.assertEqual(result['explanation'], expected['explanation'])

    def test_missing_explanation(self):
        md_block = """
# Question 2
Question without explanation.
- [x] Correct Answer
- [ ] Wrong Answer
        """
        result = parse_single_question_block(md_block)
        self.assertEqual(result['text'], 'Question without explanation.')
        self.assertEqual(result['option_a'], 'Correct Answer')
        self.assertEqual(result['option_b'], 'Wrong Answer')
        self.assertEqual(result['correct_option'], 'A')
        self.assertEqual(result['explanation'], '') # Expect empty string or specific handling

    def test_missing_options(self):
        md_block = """
# Question 3
Question with only two options.
- [ ] Opt1
- [x] Opt2
Explanation: Some details.
        """
        result = parse_single_question_block(md_block)
        self.assertEqual(result['text'], 'Question with only two options.')
        self.assertEqual(result['option_a'], 'Opt1')
        self.assertEqual(result['option_b'], 'Opt2')
        self.assertEqual(result['option_c'], '') # Expect empty
        self.assertEqual(result['option_d'], '') # Expect empty
        self.assertEqual(result['correct_option'], 'B')
        self.assertEqual(result['explanation'], 'Some details.')

    def test_spacing_variations(self):
        md_block = """
Question with weird spacing.
- [ ]OptionA
- [x]   Option B (Correct)  
Explanation:    Spaced out explanation.
        """
        result = parse_single_question_block(md_block)
        self.assertEqual(result['text'], 'Question with weird spacing.')
        self.assertEqual(result['option_a'], 'OptionA')
        self.assertEqual(result['option_b'], 'Option B (Correct)')
        self.assertEqual(result['correct_option'], 'B')
        self.assertEqual(result['explanation'], 'Spaced out explanation.')

    def test_only_question_text(self):
        md_block = "Just a question text, no options, no explanation."
        result = parse_single_question_block(md_block)
        self.assertEqual(result['text'], 'Just a question text, no options, no explanation.')
        self.assertEqual(result['option_a'], '')
        self.assertEqual(result['correct_option'], '')
        self.assertEqual(result['explanation'], '')

    def test_empty_block(self):
        md_block = ""
        result = parse_single_question_block(md_block)
        # Expect all fields to be empty or default
        self.assertEqual(result['text'], '')
        self.assertEqual(result['option_a'], '')
        self.assertEqual(result['correct_option'], '')
        self.assertEqual(result['explanation'], '')

    def test_malformed_block(self):
        # Example: No proper list items, or unusual characters
        md_block = "This is mostly text with some - [ ] maybe an option but not really."
        result = parse_single_question_block(md_block)
        # Behavior for malformed blocks can be defined by how robust the parser is.
        # For now, we expect it to extract what it can.
        self.assertIn('This is mostly text', result['text'])
        # Add more specific assertions based on desired behavior for malformed inputs

    def test_parse_multiple_questions(self):
        md_content = """
# Q1
Text for Q1
- [x] C1
- [ ] W1
Explanation: E1
---
# Q2
Text for Q2
- [ ] W2
- [x] C2
Explanation: E2
        """
        results = parse_markdown_questions(md_content)
        self.assertEqual(len(results), 2)
        
        q1 = results[0]
        self.assertEqual(q1['text'], 'Text for Q1')
        self.assertEqual(q1['option_a'], 'C1')
        self.assertEqual(q1['correct_option'], 'A')
        self.assertEqual(q1['explanation'], 'E1')
        
        q2 = results[1]
        self.assertEqual(q2['text'], 'Text for Q2')
        self.assertEqual(q2['option_b'], 'C2') # Option B is correct
        self.assertEqual(q2['correct_option'], 'B')
        self.assertEqual(q2['explanation'], 'E2')

class TestGetQuestionFilePath(unittest.TestCase):
    TEST_DIR_BASE = "temp_test_dir_for_paths"

    def setUp(self):
        # Create a temporary directory structure for testing
        self.base_folder = os.path.join(os.getcwd(), self.TEST_DIR_BASE)
        self.sub_folder = os.path.join(self.base_folder, "subdir")
        os.makedirs(self.sub_folder, exist_ok=True)

        # Create dummy files
        with open(os.path.join(self.base_folder, "questions.md"), "w") as f:
            f.write("dummy content base")
        with open(os.path.join(self.sub_folder, "another_questions.md"), "w") as f:
            f.write("dummy content sub")
        with open(os.path.join(self.sub_folder, "questions.md"), "w") as f: # Same name in subdir
            f.write("dummy content sub questions.md")

    def tearDown(self):
        # Remove the temporary directory structure
        if os.path.exists(self.base_folder):
            shutil.rmtree(self.base_folder)

    def test_file_in_base_folder(self):
        expected_path = os.path.join(self.base_folder, "questions.md")
        self.assertEqual(get_question_file_path(self.base_folder, "questions.md"), expected_path)

    def test_file_in_subfolder(self):
        # get_question_file_path currently finds the first one, which would be in base_folder if names collide.
        # Let's test for a unique name in subfolder.
        expected_path = os.path.join(self.sub_folder, "another_questions.md")
        self.assertEqual(get_question_file_path(self.base_folder, "another_questions.md"), expected_path)
        
        # Test for the questions.md in subdir specifically if base_folder is the subdir itself
        expected_path_sub = os.path.join(self.sub_folder, "questions.md")
        self.assertEqual(get_question_file_path(self.sub_folder, "questions.md"), expected_path_sub)


    def test_file_not_found(self):
        self.assertIsNone(get_question_file_path(self.base_folder, "non_existent_file.md"))

    def test_base_folder_does_not_exist(self):
        non_existent_folder = os.path.join(self.base_folder, "non_existent_base")
        self.assertIsNone(get_question_file_path(non_existent_folder, "questions.md"))

    def test_filename_is_none_or_empty(self):
        self.assertIsNone(get_question_file_path(self.base_folder, None))
        self.assertIsNone(get_question_file_path(self.base_folder, ""))

    def test_base_folder_is_none_or_empty(self):
        self.assertIsNone(get_question_file_path(None, "questions.md"))
        self.assertIsNone(get_question_file_path("", "questions.md"))

if __name__ == '__main__':
    print("Running MCQ Platform Unit Tests...")
    print("To run these tests, navigate to the root of the repository and use:")
    print("python -m unittest tests.test_app_utils")
    print("======================================================================")
    unittest.main()
