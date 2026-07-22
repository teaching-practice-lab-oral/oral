"""current schema baseline

Revision ID: 001
Revises: None
Create Date: 2026-07-18
"""

from alembic import op
import sqlalchemy as sa


revision = "001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA_STATEMENTS = ['CREATE TABLE email_jobs (\n'
 '\tid VARCHAR(36) NOT NULL, \n'
 '\tkind VARCHAR(32) NOT NULL, \n'
 '\ttotal INTEGER NOT NULL, \n'
 '\tsent INTEGER NOT NULL, \n'
 '\tfailed INTEGER NOT NULL, \n'
 "\tdone BOOLEAN DEFAULT 'false' NOT NULL, \n"
 '\tfailed_emails JSONB, \n'
 '\tcreated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tupdated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tCONSTRAINT ck_email_jobs_total_nonnegative CHECK (total >= 0), \n'
 '\tCONSTRAINT ck_email_jobs_sent_nonnegative CHECK (sent >= 0), \n'
 '\tCONSTRAINT ck_email_jobs_failed_nonnegative CHECK (failed >= 0)\n'
 ')',
 'CREATE TABLE object_deletion_tasks (\n'
 '\tid SERIAL NOT NULL, \n'
 "\ttarget_type VARCHAR(16) DEFAULT 'prefix' NOT NULL, \n"
 '\ttarget VARCHAR(512) NOT NULL, \n'
 "\tattempts INTEGER DEFAULT '0' NOT NULL, \n"
 '\tnext_attempt_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tlast_error TEXT, \n'
 '\tcompleted_at TIMESTAMP WITHOUT TIME ZONE, \n'
 '\tcreated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tCONSTRAINT uq_object_deletion_tasks_target UNIQUE (target_type, target), \n'
 "\tCONSTRAINT ck_object_deletion_tasks_target_type CHECK (target_type IN ('key', 'prefix')), \n"
 '\tCONSTRAINT ck_object_deletion_tasks_attempts_nonnegative CHECK (attempts >= 0)\n'
 ')',
 'CREATE TABLE submission_grade_revisions (\n'
 '\tid SERIAL NOT NULL, \n'
 '\torigin_submission_id INTEGER NOT NULL, \n'
 '\torigin_assignment_id INTEGER NOT NULL, \n'
 '\torigin_user_id INTEGER NOT NULL, \n'
 '\trevision_number INTEGER NOT NULL, \n'
 '\trubric_version_id INTEGER NOT NULL, \n'
 '\trubric_name VARCHAR(200) NOT NULL, \n'
 '\trubric_version_number INTEGER NOT NULL, \n'
 '\trubric_snapshot JSONB NOT NULL, \n'
 '\tratings_json JSONB NOT NULL, \n'
 '\trubric_score NUMERIC(5, 2) NOT NULL, \n'
 '\tfinal_score NUMERIC(4, 1) NOT NULL, \n'
 '\tteacher_comment TEXT NOT NULL, \n'
 '\tteacher_feedback TEXT NOT NULL, \n'
 '\tchange_reason TEXT, \n'
 '\tgrader_user_id INTEGER NOT NULL, \n'
 '\tgrader_student_id VARCHAR(64) NOT NULL, \n'
 '\tgrader_name VARCHAR(128), \n'
 '\tstudent_id_snapshot VARCHAR(64) NOT NULL, \n'
 '\tstudent_name_snapshot VARCHAR(128) NOT NULL, \n'
 '\tassignment_title_snapshot VARCHAR(256) NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tCONSTRAINT uq_grade_revisions_submission_revision UNIQUE (origin_submission_id, revision_number), \n'
 '\tCONSTRAINT ck_grade_revisions_revision_positive CHECK (revision_number >= 1), \n'
 '\tCONSTRAINT ck_grade_revisions_rubric_score CHECK (rubric_score BETWEEN 0 AND 100), \n'
 '\tCONSTRAINT ck_grade_revisions_final_score CHECK (final_score BETWEEN 0 AND 100)\n'
 ')',
 'CREATE TABLE users (\n'
 '\tid SERIAL NOT NULL, \n'
 '\tstudent_id VARCHAR(64) NOT NULL, \n'
 '\tname VARCHAR(128) NOT NULL, \n'
 '\temail VARCHAR(256) NOT NULL, \n'
 '\tbackup_email VARCHAR(256), \n'
 '\thashed_password VARCHAR(256) NOT NULL, \n'
 '\trole VARCHAR(16) NOT NULL, \n'
 '\tcourse_num VARCHAR(64), \n'
 '\tis_active BOOLEAN NOT NULL, \n'
 "\tmust_change_password BOOLEAN DEFAULT 'false' NOT NULL, \n"
 '\tprivacy_notice_version VARCHAR(32), \n'
 '\tprivacy_acknowledged_at TIMESTAMP WITHOUT TIME ZONE, \n'
 '\tsystem_terms_version VARCHAR(32), \n'
 '\tsystem_terms_accepted_at TIMESTAMP WITHOUT TIME ZONE, \n'
 "\tsession_version INTEGER DEFAULT '1' NOT NULL, \n"
 "\tfailed_login_count INTEGER DEFAULT '0' NOT NULL, \n"
 '\tlocked_until TIMESTAMP WITHOUT TIME ZONE, \n'
 '\tcreated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tupdated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 "\tCONSTRAINT ck_users_role CHECK (role IN ('student', 'admin')), \n"
 "\tCONSTRAINT ck_users_admin_backup_email_null CHECK (role = 'student' OR backup_email IS NULL), \n"
 '\tCONSTRAINT ck_users_session_version_positive CHECK (session_version >= 1), \n'
 '\tCONSTRAINT ck_users_failed_login_count_nonnegative CHECK (failed_login_count >= 0), \n'
 '\tCONSTRAINT ck_users_privacy_ack_pair CHECK ((privacy_notice_version IS NULL) = (privacy_acknowledged_at IS '
 'NULL)), \n'
 '\tCONSTRAINT ck_users_terms_ack_pair CHECK ((system_terms_version IS NULL) = (system_terms_accepted_at IS NULL))\n'
 ')',
 'CREATE TABLE active_sessions (\n'
 '\tid SERIAL NOT NULL, \n'
 '\ttoken_hash VARCHAR(64) NOT NULL, \n'
 '\tuser_id INTEGER NOT NULL, \n'
 '\tip_address VARCHAR(64), \n'
 '\tuser_agent VARCHAR(512), \n'
 '\tdevice_type VARCHAR(32), \n'
 '\tcreated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tlast_seen_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, \n'
 '\texpires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 "\tCONSTRAINT ck_active_sessions_device_type CHECK (device_type IS NULL OR device_type IN ('mobile', 'tablet', "
 "'desktop', 'unknown')), \n"
 '\tCONSTRAINT ck_active_sessions_expires_after_created CHECK (expires_at >= created_at), \n'
 '\tUNIQUE (token_hash), \n'
 '\tFOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE\n'
 ')',
 'CREATE TABLE admin_audit_logs (\n'
 '\tid SERIAL NOT NULL, \n'
 '\tadmin_user_id INTEGER, \n'
 '\tadmin_student_id VARCHAR(64) NOT NULL, \n'
 '\tadmin_name VARCHAR(128), \n'
 '\taction VARCHAR(64) NOT NULL, \n'
 '\ttarget_type VARCHAR(32), \n'
 '\ttarget_id VARCHAR(64), \n'
 '\ttarget_label VARCHAR(256), \n'
 "\tresult VARCHAR(16) DEFAULT 'success' NOT NULL, \n"
 '\tsummary TEXT, \n'
 '\tbefore_json JSONB, \n'
 '\tafter_json JSONB, \n'
 '\tdetail_json JSONB, \n'
 '\tip_address VARCHAR(64), \n'
 '\tuser_agent VARCHAR(512), \n'
 '\tcreated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 "\tCONSTRAINT ck_admin_audit_logs_result CHECK (result IN ('success', 'failure')), \n"
 '\tFOREIGN KEY(admin_user_id) REFERENCES users (id) ON DELETE SET NULL\n'
 ')',
 'CREATE TABLE api_usage_logs (\n'
 '\tid SERIAL NOT NULL, \n'
 '\tuser_id INTEGER NOT NULL, \n'
 '\tstage INTEGER NOT NULL, \n'
 '\tcalled_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tCONSTRAINT ck_api_usage_logs_stage CHECK (stage IN (1, 3, 5, 6, 7)), \n'
 '\tFOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE\n'
 ')',
 'CREATE TABLE login_events (\n'
 '\tid SERIAL NOT NULL, \n'
 '\tuser_id INTEGER, \n'
 '\tstudent_id VARCHAR(64) NOT NULL, \n'
 '\tip_address VARCHAR(64), \n'
 '\tuser_agent VARCHAR(512), \n'
 '\tdevice_type VARCHAR(32), \n'
 '\tsuccess BOOLEAN NOT NULL, \n'
 '\tlogin_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 "\tCONSTRAINT ck_login_events_device_type CHECK (device_type IS NULL OR device_type IN ('mobile', 'tablet', "
 "'desktop', 'unknown')), \n"
 '\tFOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL\n'
 ')',
 'CREATE TABLE password_reset_tokens (\n'
 '\tid SERIAL NOT NULL, \n'
 '\tuser_id INTEGER NOT NULL, \n'
 '\ttoken_hash VARCHAR(64) NOT NULL, \n'
 '\trequest_ip VARCHAR(64), \n'
 '\tcreated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, \n'
 '\texpires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tused_at TIMESTAMP WITHOUT TIME ZONE, \n'
 '\tPRIMARY KEY (id), \n'
 '\tCONSTRAINT ck_password_reset_tokens_expires_after_created CHECK (expires_at >= created_at), \n'
 '\tFOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, \n'
 '\tUNIQUE (token_hash)\n'
 ')',
 'CREATE TABLE prompt_templates (\n'
 '\tid SERIAL NOT NULL, \n'
 '\tstage INTEGER NOT NULL, \n'
 '\tname VARCHAR(200), \n'
 "\tis_system BOOLEAN DEFAULT 'false' NOT NULL, \n"
 '\tsystem_prompt TEXT NOT NULL, \n'
 '\troleplay_policy TEXT, \n'
 '\tsecret_question_policy TEXT, \n'
 '\tupdated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tupdated_by INTEGER, \n'
 '\tPRIMARY KEY (id), \n'
 '\tCONSTRAINT ck_prompt_templates_stage CHECK (stage IN (3, 6, 8)), \n'
 "\tCONSTRAINT ck_prompt_templates_stage_policies CHECK ((stage = 6 AND NULLIF(BTRIM(roleplay_policy), '') IS NOT "
 "NULL AND NULLIF(BTRIM(secret_question_policy), '') IS NOT NULL) OR (stage <> 6 AND roleplay_policy IS NULL AND "
 'secret_question_policy IS NULL)), \n'
 '\tFOREIGN KEY(updated_by) REFERENCES users (id) ON DELETE SET NULL\n'
 ')',
 'CREATE TABLE rubrics (\n'
 '\tid SERIAL NOT NULL, \n'
 '\tname VARCHAR(200) NOT NULL, \n'
 '\tdescription TEXT, \n'
 "\tis_system BOOLEAN DEFAULT 'false' NOT NULL, \n"
 "\tis_archived BOOLEAN DEFAULT 'false' NOT NULL, \n"
 '\tcreated_by INTEGER, \n'
 '\tcreated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tupdated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tFOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL\n'
 ')',
 'CREATE TABLE rubric_versions (\n'
 '\tid SERIAL NOT NULL, \n'
 '\trubric_id INTEGER NOT NULL, \n'
 '\tversion_number INTEGER NOT NULL, \n'
 "\tstatus VARCHAR(16) DEFAULT 'draft' NOT NULL, \n"
 '\tdefinition JSONB NOT NULL, \n'
 '\tcreated_by INTEGER, \n'
 '\tcreated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tpublished_at TIMESTAMP WITHOUT TIME ZONE, \n'
 '\tPRIMARY KEY (id), \n'
 '\tCONSTRAINT uq_rubric_versions_rubric_version UNIQUE (rubric_id, version_number), \n'
 '\tCONSTRAINT ck_rubric_versions_number_positive CHECK (version_number >= 1), \n'
 "\tCONSTRAINT ck_rubric_versions_status CHECK (status IN ('draft', 'published')), \n"
 "\tCONSTRAINT ck_rubric_versions_definition_object CHECK (jsonb_typeof(definition) = 'object'), \n"
 '\tFOREIGN KEY(rubric_id) REFERENCES rubrics (id) ON DELETE CASCADE, \n'
 '\tFOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL\n'
 ')',
 'CREATE TABLE student_presence (\n'
 '\tuser_id INTEGER NOT NULL, \n'
 '\tactive_session_id INTEGER, \n'
 '\tip_address VARCHAR(64), \n'
 '\tdevice_type VARCHAR(32), \n'
 '\tlast_seen_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, \n'
 '\texpires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (user_id), \n'
 "\tCONSTRAINT ck_student_presence_device_type CHECK (device_type IS NULL OR device_type IN ('mobile', 'tablet', "
 "'desktop', 'unknown')), \n"
 '\tCONSTRAINT ck_student_presence_expires_after_seen CHECK (expires_at >= last_seen_at), \n'
 '\tFOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, \n'
 '\tUNIQUE (active_session_id), \n'
 '\tFOREIGN KEY(active_session_id) REFERENCES active_sessions (id) ON DELETE SET NULL\n'
 ')',
 'CREATE TABLE assignments (\n'
 '\tid SERIAL NOT NULL, \n'
 '\ttitle VARCHAR(256) NOT NULL, \n'
 '\tdescription TEXT, \n'
 '\tquestions JSONB NOT NULL, \n'
 '\tquestion_set_key VARCHAR(64), \n'
 '\tcourse_nums JSONB, \n'
 '\tstart_date TIMESTAMP WITHOUT TIME ZONE, \n'
 '\tdue_date TIMESTAMP WITHOUT TIME ZONE, \n'
 '\tprompt_context TEXT, \n'
 '\tstage3_template_id INTEGER, \n'
 '\tstage6_template_id INTEGER, \n'
 '\tstage8_template_id INTEGER, \n'
 '\trubric_version_id INTEGER NOT NULL, \n'
 '\tis_active BOOLEAN NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tupdated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tcreated_by INTEGER, \n'
 '\tPRIMARY KEY (id), \n'
 '\tCONSTRAINT ck_assignments_due_after_start CHECK (start_date IS NULL OR due_date IS NULL OR due_date >= '
 'start_date), \n'
 "\tCONSTRAINT ck_assignments_course_nums_array CHECK (course_nums IS NULL OR jsonb_typeof(course_nums) IN ('array', "
 "'null')), \n"
 "\tCONSTRAINT ck_assignments_questions_array CHECK (questions IS NULL OR jsonb_typeof(questions) IN ('array', "
 "'null')), \n"
 "\tCONSTRAINT ck_assignments_questions_four CHECK (CASE WHEN jsonb_typeof(questions) = 'array' THEN CASE WHEN "
 "jsonb_array_length(questions) = 4 THEN jsonb_typeof(questions->0) = 'string' AND btrim(questions->>0) <> '' AND "
 "jsonb_typeof(questions->1) = 'string' AND btrim(questions->>1) <> '' AND jsonb_typeof(questions->2) = 'string' AND "
 "btrim(questions->>2) <> '' AND jsonb_typeof(questions->3) = 'string' AND btrim(questions->>3) <> '' ELSE FALSE END "
 'ELSE FALSE END), \n'
 '\tCONSTRAINT ck_assignments_question_set_key CHECK (question_set_key IS NULL OR question_set_key IN '
 "('background_motivation', 'skills_achievements', 'situational_problem_solving', 'work_attitude_soft_skills', "
 "'company_future')), \n"
 '\tFOREIGN KEY(stage3_template_id) REFERENCES prompt_templates (id) ON DELETE SET NULL, \n'
 '\tFOREIGN KEY(stage6_template_id) REFERENCES prompt_templates (id) ON DELETE SET NULL, \n'
 '\tFOREIGN KEY(stage8_template_id) REFERENCES prompt_templates (id) ON DELETE SET NULL, \n'
 '\tFOREIGN KEY(rubric_version_id) REFERENCES rubric_versions (id) ON DELETE RESTRICT, \n'
 '\tFOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL\n'
 ')',
 'CREATE TABLE assignment_reminders (\n'
 '\tid SERIAL NOT NULL, \n'
 '\tassignment_id INTEGER NOT NULL, \n'
 '\tuser_id INTEGER NOT NULL, \n'
 '\tsent_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tCONSTRAINT uq_assignment_reminder UNIQUE (assignment_id, user_id), \n'
 '\tFOREIGN KEY(assignment_id) REFERENCES assignments (id) ON DELETE CASCADE, \n'
 '\tFOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE\n'
 ')',
 'CREATE TABLE submissions (\n'
 '\tid SERIAL NOT NULL, \n'
 '\tuser_id INTEGER NOT NULL, \n'
 '\tassignment_id INTEGER NOT NULL, \n'
 '\tquestion_set_key VARCHAR(64), \n'
 '\tattempt_number INTEGER NOT NULL, \n'
 '\tstage INTEGER NOT NULL, \n'
 "\tworkflow_version INTEGER DEFAULT '2' NOT NULL, \n"
 '\trubric_version_id INTEGER NOT NULL, \n'
 '\tdraft2_ai_feedback JSONB, \n'
 "\tfeedback_count INTEGER DEFAULT '0' NOT NULL, \n"
 '\tlate_deadline TIMESTAMP WITHOUT TIME ZONE, \n'
 '\tpractice_started_at TIMESTAMP WITHOUT TIME ZONE, \n'
 '\tpractice_deadline_at TIMESTAMP WITHOUT TIME ZONE, \n'
 '\tpractice_completed_at TIMESTAMP WITHOUT TIME ZONE, \n'
 '\tsubmitted_at TIMESTAMP WITHOUT TIME ZONE, \n'
 '\tupdated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tCONSTRAINT uq_submission_attempt UNIQUE (user_id, assignment_id, attempt_number), \n'
 '\tCONSTRAINT ck_submissions_attempt_positive CHECK (attempt_number >= 1), \n'
 '\tCONSTRAINT ck_submissions_stage_range CHECK (stage BETWEEN 1 AND 9), \n'
 '\tCONSTRAINT ck_submissions_workflow_version CHECK (workflow_version = 2), \n'
 '\tCONSTRAINT ck_submissions_feedback_count_nonnegative CHECK (feedback_count >= 0), \n'
 '\tCONSTRAINT ck_submissions_question_set_key CHECK (question_set_key IS NULL OR question_set_key IN '
 "('background_motivation', 'skills_achievements', 'situational_problem_solving', 'work_attitude_soft_skills', "
 "'company_future')), \n"
 '\tCONSTRAINT ck_submissions_submitted_stage CHECK (submitted_at IS NULL OR stage >= 9), \n'
 '\tFOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, \n'
 '\tFOREIGN KEY(assignment_id) REFERENCES assignments (id) ON DELETE CASCADE, \n'
 '\tFOREIGN KEY(rubric_version_id) REFERENCES rubric_versions (id) ON DELETE RESTRICT\n'
 ')',
 'CREATE TABLE roleplay_turns (\n'
 '\tid SERIAL NOT NULL, \n'
 '\tsubmission_id INTEGER NOT NULL, \n'
 '\tturn_number INTEGER NOT NULL, \n'
 '\tsource_question_index INTEGER, \n'
 '\tinterviewer_question TEXT NOT NULL, \n'
 '\tinterviewer_tts_key VARCHAR(512), \n'
 '\tstudent_transcript TEXT, \n'
 '\tstudent_audio_key VARCHAR(512), \n'
 '\tstudent_metrics JSONB, \n'
 '\tcreated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tupdated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tCONSTRAINT uq_roleplay_turns_submission_turn UNIQUE (submission_id, turn_number), \n'
 '\tCONSTRAINT ck_roleplay_turns_turn_positive CHECK (turn_number >= 1), \n'
 '\tCONSTRAINT ck_roleplay_turns_source_question_index CHECK (source_question_index IS NULL OR source_question_index '
 'BETWEEN 0 AND 4), \n'
 '\tFOREIGN KEY(submission_id) REFERENCES submissions (id) ON DELETE CASCADE\n'
 ')',
 'CREATE TABLE shadowing_records (\n'
 '\tid SERIAL NOT NULL, \n'
 '\tsubmission_id INTEGER NOT NULL, \n'
 '\tquestion_index INTEGER NOT NULL, \n'
 '\ttts_key VARCHAR(512), \n'
 '\ttts_timing JSONB, \n'
 '\taudio_key VARCHAR(512), \n'
 '\ttranscript TEXT, \n'
 '\tmetrics JSONB, \n'
 "\tattempts INTEGER DEFAULT '0' NOT NULL, \n"
 '\tcreated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tupdated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tCONSTRAINT uq_shadowing_records_submission_index UNIQUE (submission_id, question_index), \n'
 '\tCONSTRAINT ck_shadowing_records_index_nonnegative CHECK (question_index >= 0), \n'
 '\tCONSTRAINT ck_shadowing_records_attempts_nonnegative CHECK (attempts >= 0), \n'
 '\tFOREIGN KEY(submission_id) REFERENCES submissions (id) ON DELETE CASCADE\n'
 ')',
 'CREATE TABLE submission_answers (\n'
 '\tid SERIAL NOT NULL, \n'
 '\tsubmission_id INTEGER NOT NULL, \n'
 '\tanswer_type VARCHAR(16) NOT NULL, \n'
 '\tquestion_index INTEGER NOT NULL, \n'
 '\tquestion_text TEXT NOT NULL, \n'
 '\tanswer_text TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tupdated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tCONSTRAINT uq_submission_answers_type_index UNIQUE (submission_id, answer_type, question_index), \n'
 "\tCONSTRAINT ck_submission_answers_type CHECK (answer_type IN ('draft1', 'final')), \n"
 '\tCONSTRAINT ck_submission_answers_index_nonnegative CHECK (question_index >= 0), \n'
 '\tFOREIGN KEY(submission_id) REFERENCES submissions (id) ON DELETE CASCADE\n'
 ')',
 'CREATE TABLE submission_job_profiles (\n'
 '\tid SERIAL NOT NULL, \n'
 '\tsubmission_id INTEGER NOT NULL, \n'
 '\tdesired_position VARCHAR(200) NOT NULL, \n'
 '\trole_description TEXT NOT NULL, \n'
 '\trequired_competencies TEXT NOT NULL, \n'
 '\tadditional_notes TEXT, \n'
 '\tlearning_scaffold JSONB, \n'
 '\tscaffold_input_hash VARCHAR(64), \n'
 '\tscaffold_generated_at TIMESTAMP WITHOUT TIME ZONE, \n'
 '\tcreated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tupdated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tCONSTRAINT uq_submission_job_profiles_submission_id UNIQUE (submission_id), \n'
 '\tFOREIGN KEY(submission_id) REFERENCES submissions (id) ON DELETE CASCADE\n'
 ')',
 'CREATE TABLE submission_proctor_events (\n'
 '\tid SERIAL NOT NULL, \n'
 '\tsubmission_id INTEGER NOT NULL, \n'
 '\tevent_type VARCHAR(32) NOT NULL, \n'
 '\tpage_path VARCHAR(160) NOT NULL, \n'
 '\tdetails JSONB, \n'
 '\tcreated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 "\tCONSTRAINT ck_submission_proctor_events_type CHECK (event_type IN ('fullscreen_enter', 'fullscreen_exit', "
 "'page_hidden', 'window_blur', 'paste_blocked', 'large_input', 'time_expired')), \n"
 '\tFOREIGN KEY(submission_id) REFERENCES submissions (id) ON DELETE CASCADE\n'
 ')',
 'CREATE TABLE submission_questions (\n'
 '\tid SERIAL NOT NULL, \n'
 '\tsubmission_id INTEGER NOT NULL, \n'
 '\tquestion_index INTEGER NOT NULL, \n'
 '\tquestion_text TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tCONSTRAINT uq_submission_questions_submission_index UNIQUE (submission_id, question_index), \n'
 '\tCONSTRAINT ck_submission_questions_index_nonnegative CHECK (question_index >= 0), \n'
 '\tFOREIGN KEY(submission_id) REFERENCES submissions (id) ON DELETE CASCADE\n'
 ')',
 'CREATE TABLE submission_reflections (\n'
 '\tid SERIAL NOT NULL, \n'
 '\tsubmission_id INTEGER NOT NULL, \n'
 "\thas_issue BOOLEAN DEFAULT 'false' NOT NULL, \n"
 '\tissue_category VARCHAR(32), \n'
 '\tissue_description TEXT, \n'
 '\tphoto_key VARCHAR(512), \n'
 '\tphoto_content_type VARCHAR(64), \n'
 '\tphoto_original_name VARCHAR(256), \n'
 '\tphoto_size INTEGER, \n'
 "\trevision INTEGER DEFAULT '1' NOT NULL, \n"
 '\tsubmitted_at TIMESTAMP WITHOUT TIME ZONE, \n'
 '\tcreated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tupdated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tCONSTRAINT uq_submission_reflections_submission_id UNIQUE (submission_id), \n'
 '\tCONSTRAINT ck_submission_reflections_issue_detail CHECK (submitted_at IS NULL OR NOT has_issue OR '
 "(issue_category IS NOT NULL AND btrim(issue_category) <> '' AND issue_description IS NOT NULL AND "
 "btrim(issue_description) <> '')), \n"
 '\tCONSTRAINT ck_submission_reflections_photo_size CHECK (photo_size IS NULL OR photo_size BETWEEN 1 AND '
 '10485760), \n'
 '\tCONSTRAINT ck_submission_reflections_revision_positive CHECK (revision >= 1), \n'
 '\tFOREIGN KEY(submission_id) REFERENCES submissions (id) ON DELETE CASCADE\n'
 ')',
 'CREATE TABLE submission_reports (\n'
 '\tid SERIAL NOT NULL, \n'
 '\tsubmission_id INTEGER NOT NULL, \n'
 '\treport_data JSONB NOT NULL, \n'
 '\tinput_hash VARCHAR(64), \n'
 '\tcreated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tupdated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tCONSTRAINT uq_submission_reports_submission_id UNIQUE (submission_id), \n'
 '\tFOREIGN KEY(submission_id) REFERENCES submissions (id) ON DELETE CASCADE\n'
 ')',
 'CREATE TABLE worker_routing_events (\n'
 '\tid SERIAL NOT NULL, \n'
 '\tuser_id INTEGER, \n'
 '\tstudent_id VARCHAR(64) NOT NULL, \n'
 '\tsubmission_id INTEGER, \n'
 '\tstage INTEGER, \n'
 '\toperation VARCHAR(64) NOT NULL, \n'
 '\troute_status VARCHAR(32) NOT NULL, \n'
 '\tworker_url VARCHAR(512), \n'
 '\tdetail VARCHAR(256), \n'
 '\tduration_ms INTEGER, \n'
 '\tcreated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 "\tCONSTRAINT ck_worker_routing_events_status CHECK (route_status IN ('worker_success', 'fallback_error', "
 "'local_weight', 'local_cooldown', 'local_disabled')), \n"
 '\tCONSTRAINT ck_worker_routing_events_stage CHECK (stage IS NULL OR stage BETWEEN 1 AND 8), \n'
 '\tCONSTRAINT ck_worker_routing_events_duration CHECK (duration_ms IS NULL OR duration_ms >= 0), \n'
 '\tFOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL, \n'
 '\tFOREIGN KEY(submission_id) REFERENCES submissions (id) ON DELETE SET NULL\n'
 ')',
 'CREATE TABLE submission_reflection_answers (\n'
 '\tid SERIAL NOT NULL, \n'
 '\treflection_id INTEGER NOT NULL, \n'
 '\tquestion_index INTEGER NOT NULL, \n'
 '\tquestion_text TEXT NOT NULL, \n'
 '\tanswer_text TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tupdated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tCONSTRAINT uq_reflection_answers_reflection_index UNIQUE (reflection_id, question_index), \n'
 '\tCONSTRAINT ck_reflection_answers_index_nonnegative CHECK (question_index >= 0), \n'
 '\tFOREIGN KEY(reflection_id) REFERENCES submission_reflections (id) ON DELETE CASCADE\n'
 ')',
 'CREATE INDEX ix_object_deletion_tasks_completed_at ON object_deletion_tasks (completed_at)',
 'CREATE INDEX ix_object_deletion_tasks_next_attempt_at ON object_deletion_tasks (next_attempt_at)',
 'CREATE INDEX ix_object_deletion_tasks_pending ON object_deletion_tasks (next_attempt_at) WHERE completed_at IS '
 'NULL',
 'CREATE INDEX ix_grade_revisions_assignment_created ON submission_grade_revisions (origin_assignment_id, created_at '
 'DESC)',
 'CREATE INDEX ix_grade_revisions_submission_latest ON submission_grade_revisions (origin_submission_id, created_at '
 'DESC, id DESC)',
 'CREATE INDEX ix_users_course_num ON users (course_num)',
 'CREATE INDEX ix_users_is_active_role ON users (is_active, role)',
 'CREATE UNIQUE INDEX ix_users_student_id ON users (student_id)',
 'CREATE INDEX ix_active_sessions_expires_at ON active_sessions (expires_at)',
 'CREATE INDEX ix_active_sessions_last_seen_expires ON active_sessions (last_seen_at, expires_at)',
 'CREATE INDEX ix_active_sessions_user_id ON active_sessions (user_id)',
 'CREATE INDEX ix_admin_audit_logs_action ON admin_audit_logs (action)',
 'CREATE INDEX ix_admin_audit_logs_action_created ON admin_audit_logs (action, created_at DESC)',
 'CREATE INDEX ix_admin_audit_logs_admin_student_id ON admin_audit_logs (admin_student_id)',
 'CREATE INDEX ix_admin_audit_logs_admin_user_id ON admin_audit_logs (admin_user_id)',
 'CREATE INDEX ix_admin_audit_logs_created_at ON admin_audit_logs (created_at)',
 'CREATE INDEX ix_admin_audit_logs_created_id_desc ON admin_audit_logs (created_at DESC, id DESC)',
 'CREATE INDEX ix_admin_audit_logs_target_id ON admin_audit_logs (target_id)',
 'CREATE INDEX ix_admin_audit_logs_target_type ON admin_audit_logs (target_type)',
 'CREATE INDEX ix_admin_audit_logs_target_type_created ON admin_audit_logs (target_type, created_at DESC)',
 'CREATE INDEX ix_api_usage_user_called ON api_usage_logs (user_id, called_at)',
 'CREATE INDEX ix_api_usage_user_stage_called ON api_usage_logs (user_id, stage, called_at)',
 'CREATE INDEX ix_login_events_ip_login_at ON login_events (ip_address, login_at)',
 'CREATE INDEX ix_login_events_login_at ON login_events (login_at)',
 'CREATE INDEX ix_login_events_student_id ON login_events (student_id)',
 'CREATE INDEX ix_login_events_success_login_at ON login_events (success, login_at DESC)',
 'CREATE INDEX ix_login_events_user_login_at ON login_events (user_id, login_at DESC)',
 'CREATE INDEX ix_password_reset_tokens_created_at ON password_reset_tokens (created_at)',
 'CREATE INDEX ix_password_reset_tokens_expires_at ON password_reset_tokens (expires_at)',
 'CREATE INDEX ix_password_reset_tokens_ip_created ON password_reset_tokens (request_ip, created_at DESC)',
 'CREATE INDEX ix_password_reset_tokens_request_ip ON password_reset_tokens (request_ip)',
 'CREATE INDEX ix_password_reset_tokens_user_created ON password_reset_tokens (user_id, created_at DESC)',
 'CREATE INDEX ix_password_reset_tokens_user_id ON password_reset_tokens (user_id)',
 'CREATE INDEX ix_prompt_templates_global_stage_system_updated ON prompt_templates (stage, is_system, updated_at)',
 'CREATE INDEX ix_prompt_templates_updated_by ON prompt_templates (updated_by)',
 'CREATE UNIQUE INDEX uq_prompt_templates_system_stage ON prompt_templates (stage) WHERE is_system IS true',
 'CREATE INDEX ix_rubrics_archived_name ON rubrics (is_archived, name)',
 'CREATE UNIQUE INDEX uq_rubrics_single_system ON rubrics (is_system) WHERE is_system IS true',
 'CREATE INDEX ix_rubric_versions_status_created ON rubric_versions (status, created_at)',
 'CREATE INDEX ix_student_presence_expires_at ON student_presence (expires_at)',
 'CREATE INDEX ix_student_presence_last_seen ON student_presence (last_seen_at)',
 'CREATE INDEX ix_assignments_active_due_date ON assignments (is_active, due_date)',
 'CREATE INDEX ix_assignments_created_at_desc ON assignments (created_at DESC)',
 'CREATE INDEX ix_assignments_created_by ON assignments (created_by)',
 'CREATE INDEX ix_assignments_rubric_version_id ON assignments (rubric_version_id)',
 'CREATE INDEX ix_assignment_reminders_user_id ON assignment_reminders (user_id)',
 'CREATE INDEX ix_submissions_assignment_submitted ON submissions (assignment_id, submitted_at)',
 'CREATE INDEX ix_submissions_rubric_version_id ON submissions (rubric_version_id)',
 'CREATE INDEX ix_submissions_user_id ON submissions (user_id)',
 'CREATE INDEX ix_submission_job_profiles_submission_id ON submission_job_profiles (submission_id)',
 'CREATE INDEX ix_submission_proctor_events_submission_created ON submission_proctor_events (submission_id, '
 'created_at)',
 'CREATE INDEX ix_submission_reflections_issue_submitted ON submission_reflections (has_issue, submitted_at) WHERE '
 'has_issue IS true',
 'CREATE INDEX ix_submission_reflections_submission_id ON submission_reflections (submission_id)',
 'CREATE INDEX ix_worker_routing_events_created_at ON worker_routing_events (created_at)',
 'CREATE INDEX ix_worker_routing_events_created_id_desc ON worker_routing_events (created_at DESC, id DESC)',
 'CREATE INDEX ix_worker_routing_events_route_status ON worker_routing_events (route_status)',
 'CREATE INDEX ix_worker_routing_events_status_created ON worker_routing_events (route_status, created_at DESC)',
 'CREATE INDEX ix_worker_routing_events_student_id ON worker_routing_events (student_id)',
 'CREATE INDEX ix_worker_routing_events_submission_id ON worker_routing_events (submission_id)',
 'CREATE INDEX ix_worker_routing_events_user_created ON worker_routing_events (user_id, created_at DESC)',
 'CREATE INDEX ix_worker_routing_events_user_id ON worker_routing_events (user_id)',
 'CREATE INDEX ix_reflection_answers_reflection_index ON submission_reflection_answers (reflection_id, '
 'question_index)']

TABLE_NAMES = ['email_jobs',
 'object_deletion_tasks',
 'submission_grade_revisions',
 'users',
 'active_sessions',
 'admin_audit_logs',
 'api_usage_logs',
 'login_events',
 'password_reset_tokens',
 'prompt_templates',
 'rubrics',
 'rubric_versions',
 'student_presence',
 'assignments',
 'assignment_reminders',
 'submissions',
 'roleplay_turns',
 'shadowing_records',
 'submission_answers',
 'submission_job_profiles',
 'submission_proctor_events',
 'submission_questions',
 'submission_reflections',
 'submission_reports',
 'worker_routing_events',
 'submission_reflection_answers']


def upgrade():
    for statement in SCHEMA_STATEMENTS:
        op.execute(sa.text(statement))
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION prevent_grade_revision_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'submission_grade_revisions is append-only';
        END;
        $$ LANGUAGE plpgsql
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_grade_revisions_append_only
        BEFORE UPDATE OR DELETE ON submission_grade_revisions
        FOR EACH ROW EXECUTE FUNCTION prevent_grade_revision_mutation()
    """))


def downgrade():
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_grade_revisions_append_only ON submission_grade_revisions"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS prevent_grade_revision_mutation()"))
    for table_name in reversed(TABLE_NAMES):
        op.drop_table(table_name)
