# Review validation evidence

Reviewed backend commit: `33080b9021239c0a0e3d87adbf46820329234bd6`.

These are actual review-test outputs. Model/SDK responses are mocked where indicated by the source. Filesystem and command checks use synthetic temporary fixtures. They are separate from live agent missions.

Local machine and temporary-directory paths have been normalized for portability. Results, error messages, and timestamps are preserved. `<review-venv>` is the review virtual environment, and `<isolated-review>` is an isolated copy of the reviewed commit.

## core-tests

Started UTC: `2026-10-29T21:58:53.324683+00:00`. Exit code: `0`.

Command and working directory:

```text
{
  "command": [
    "<review-venv>/bin/python",
    "-m",
    "pytest",
    "tests/",
    "-q",
    "-p",
    "no:cacheprovider"
  ],
  "cwd": "<isolated-review>/devpilot"
}
```

Standard output:

```text
.....................................                                    [100%]
=============================== warnings summary ===============================
core/state.py:80
  <isolated-review>/devpilot/core/state.py:80: PytestCollectionWarning: cannot collect test class 'RunTestRecord' because it has a __init__ constructor (from: tests/test_core.py)
    @dataclass

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
37 passed, 1 warning in 0.03s
```

## mini-shop-tests

Started UTC: `2026-10-29T21:58:53.924764+00:00`. Exit code: `0`.

Command and working directory:

```text
{
  "command": [
    "<review-venv>/bin/python",
    "-m",
    "pytest",
    "tests/",
    "-q",
    "-p",
    "no:cacheprovider"
  ],
  "cwd": "<isolated-review>/devpilot/demo_repos/mini_shop"
}
```

Standard output:

```text
........                                                                 [100%]
8 passed in 0.00s
```

## revision-fixture-tests

Started UTC: `2026-10-29T21:58:54.050672+00:00`. Exit code: `1`.

Command and working directory:

```text
{
  "command": [
    "<review-venv>/bin/python",
    "-m",
    "pytest",
    "tests/",
    "-q",
    "-p",
    "no:cacheprovider",
    "--tb=short"
  ],
  "cwd": "<isolated-review>/devpilot/demo_repos/revision_repo"
}
```

Standard output:

```text
FF..                                                                     [100%]
=================================== FAILURES ===================================
____________________________ test_apply_tax_default ____________________________
tests/test_pricing.py:13: in test_apply_tax_default
    assert apply_tax(100) == 110.0
E   assert 110.00000000000001 == 110.0
E    +  where 110.00000000000001 = apply_tax(100)
_____________________________ test_checkout_total ______________________________
tests/test_pricing.py:18: in test_checkout_total
    assert checkout_total(50) == 55.0
E   assert 55.00000000000001 == 55.0
E    +  where 55.00000000000001 = checkout_total(50)
=========================== short test summary info ============================
FAILED tests/test_pricing.py::test_apply_tax_default - assert 110.00000000000...
FAILED tests/test_pricing.py::test_checkout_total - assert 55.00000000000001 ...
2 failed, 2 passed in 0.01s
```

## regression-failures

Started UTC: `2026-10-29T22:00:44.020135+00:00`. Exit code: `1`.

Command and working directory:

```text
{
  "command": [
    "<review-venv>/bin/python",
    "-m",
    "pytest",
    "test_siddharth_regressions.py",
    "-q",
    "-p",
    "no:cacheprovider",
    "--tb=long",
    "--junitxml=<review-home>/Documents/pecathon/errors-33080b9/regressions.xml"
  ],
  "cwd": "<review-home>/Documents/pecathon/branch-reviews"
}
```

Standard output:

```text
FFFFFFFFFFFFFFF                                                          [100%]
=================================== FAILURES ===================================
__________________ test_workspace_prefix_sibling_is_rejected ___________________

tmp_path = PosixPath('<pytest-temp>/pytest-11/test_workspace_prefix_sibling_0')

    def test_workspace_prefix_sibling_is_rejected(tmp_path):
        workspace = tmp_path / 'workspace'
        sibling = tmp_path / 'workspace_other'
        workspace.mkdir()
        sibling.mkdir()
        marker = sibling / 'marker.txt'
        marker.write_text('synthetic outside marker')
>       with pytest.raises(SafetyError):
             ^^^^^^^^^^^^^^^^^^^^^^^^^^
E       Failed: DID NOT RAISE SafetyError

test_siddharth_regressions.py:46: Failed
_________________________ test_file_tool_denies_dotenv _________________________

context = (SharedState(run_id='review', request='Implement the requested small change', repo_path='/private/var/folders/kr/jqmy8..., last_verify_time=''), <core.board.MessageBoard object at 0x10afa5fd0>, <core.logger.RunLogger object at 0x10afa6120>)

    def test_file_tool_denies_dotenv(context):
        state, _, _ = context
        target = Path(state.workspace_path) / '.env'
        target.write_text('REVIEW_MARKER=synthetic_value')
>       with pytest.raises(SafetyError):
             ^^^^^^^^^^^^^^^^^^^^^^^^^^
E       Failed: DID NOT RAISE SafetyError

test_siddharth_regressions.py:54: Failed
____________________ test_search_rejects_symlink_to_outside ____________________

context = (SharedState(run_id='review', request='Implement the requested small change', repo_path='/private/var/folders/kr/jqmy8..., last_verify_time=''), <core.board.MessageBoard object at 0x10af4da90>, <core.logger.RunLogger object at 0x10af4dbd0>)

    def test_search_rejects_symlink_to_outside(context):
        state, _, _ = context
        marker = Path(state.repo_path) / 'outside.py'
        marker.write_text('review_outside_marker = True')
        (Path(state.workspace_path) / 'alias.py').symlink_to(marker)
>       assert search_code('review_outside_marker', state.workspace_path) == []
E       AssertionError: assert [{'file': 'al...rker = True'}] == []
E         
E         Left contains one more item: {'file': 'alias.py', 'line': 1, 'content': 'review_outside_marker = True'}
E         Use -v to get more diff

test_siddharth_regressions.py:63: AssertionError
_____________________ test_command_rejects_shell_separator _____________________

context = (SharedState(run_id='review', request='Implement the requested small change', repo_path='/private/var/folders/kr/jqmy8..., last_verify_time=''), <core.board.MessageBoard object at 0x10af4e5d0>, <core.logger.RunLogger object at 0x10af4e710>)

    def test_command_rejects_shell_separator(context):
        state, _, _ = context
        result = run_command('ls ; printf review_shell_marker', state.workspace_path)
>       assert result['blocked'], result
E       AssertionError: {'command': 'ls ; printf review_shell_marker', 'exit_code': 0, 'stdout': 'review_shell_marker', 'stderr': '', ...}
E       assert False

test_siddharth_regressions.py:69: AssertionError
__________________ test_command_rejects_outside_file_argument __________________

context = (SharedState(run_id='review', request='Implement the requested small change', repo_path='/private/var/folders/kr/jqmy8..., last_verify_time=''), <core.board.MessageBoard object at 0x10b504b00>, <core.logger.RunLogger object at 0x10b504c30>)

    def test_command_rejects_outside_file_argument(context):
        state, _, _ = context
        marker = Path(state.repo_path) / 'marker.txt'
        marker.write_text('synthetic outside marker')
        result = run_command(f'cat {marker}', state.workspace_path)
>       assert result['blocked'], result
E       AssertionError: {'command': 'cat <pytest-temp>/pytest-11/test_command_rejects_outside_f0/original/marker.txt', 'exit_code': 0, 'stdout': 'synthetic outside marker', 'stderr': '', ...}
E       assert False

test_siddharth_regressions.py:77: AssertionError
____________________ test_developer_finishing_updates_task _____________________

context = (SharedState(run_id='review', request='Implement the requested small change', repo_path='/private/var/folders/kr/jqmy8..., last_verify_time=''), <core.board.MessageBoard object at 0x10b505940>, <core.logger.RunLogger object at 0x10b505a70>)
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x10af32690>

    def test_developer_finishing_updates_task(context, monkeypatch):
        import agents.developer as module
        state, _, _ = context
        state.tasks.append(Task('t1', 'Create answer module', 'developer'))
        agent = agent_instance(module, 'DeveloperAgent', context, monkeypatch)
    
        def simulated_loop(**kwargs):
            kwargs['dispatch_fn']('edit_file', {'path': 'answer.py', 'content': 'answer = 42\n'})
            return 'Completed task t1'
    
        monkeypatch.setattr(module, 'run_agent_loop', simulated_loop)
        agent.run()
>       assert state.tasks[0].status == TaskStatus.DONE
E       AssertionError: assert <TaskStatus.P...NG: 'pending'> == <TaskStatus.DONE: 'done'>
E         
E         - done
E         + pending

test_siddharth_regressions.py:92: AssertionError
________________ test_developer_retains_budget_after_short_run _________________

context = (SharedState(run_id='review', request='Implement the requested small change', repo_path='/private/var/folders/kr/jqmy8..., last_verify_time=''), <core.board.MessageBoard object at 0x10af479b0>, <core.logger.RunLogger object at 0x10af47ad0>)
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x10b4fc350>

    def test_developer_retains_budget_after_short_run(context, monkeypatch):
        import agents.developer as module
        state, _, _ = context
        budgets = []
    
        def simulated_one_iteration(**kwargs):
            budgets.append(kwargs['max_iterations'])
            return 'One simulated model response'
    
        monkeypatch.setattr(module, 'run_agent_loop', simulated_one_iteration)
        agent_instance(module, 'DeveloperAgent', context, monkeypatch).run()
        agent_instance(module, 'DeveloperAgent', context, monkeypatch).run()
>       assert budgets[1] > 0, budgets
E       AssertionError: [15, 0]
E       assert 0 > 0

test_siddharth_regressions.py:107: AssertionError
___________________ test_verifier_can_mark_passing_criterion ___________________

context = (SharedState(run_id='review', request='Implement the requested small change', repo_path='/private/var/folders/kr/jqmy8...2:00:44.266361+00:00'), <core.board.MessageBoard object at 0x10af33460>, <core.logger.RunLogger object at 0x10af33570>)
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x10b4fcd50>

    def test_verifier_can_mark_passing_criterion(context, monkeypatch):
        import agents.verifier as module
        state, _, _ = context
        state.criteria.append(Criterion('c1', 'Independent arithmetic check succeeds'))
        (Path(state.workspace_path) / 'probe.py').write_text('assert 2 + 2 == 4\n')
        agent = agent_instance(module, 'VerifierAgent', context, monkeypatch)
    
        def simulated_loop(**kwargs):
            output = kwargs['dispatch_fn']('run_command', {'command': 'python probe.py'})
            assert 'exit_code=0' in output
            return 'Criterion c1 passed with independent probe evidence'
    
        monkeypatch.setattr(module, 'run_agent_loop', simulated_loop)
        agent.run()
>       assert state.criteria[0].status == CriterionStatus.MET
E       AssertionError: assert <CriterionSta...NMET: 'unmet'> == <CriterionStatus.MET: 'met'>
E         
E         - met
E         + unmet
E         ? ++

test_siddharth_regressions.py:124: AssertionError
_________________ test_failing_suite_is_not_hidden_by_later_ls _________________

context = (SharedState(run_id='review', request='Implement the requested small change', repo_path='/private/var/folders/kr/jqmy8..., last_verify_time=''), <core.board.MessageBoard object at 0x10af33df0>, <core.logger.RunLogger object at 0x10af33f00>)
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x10b51ed50>

    def test_failing_suite_is_not_hidden_by_later_ls(context, monkeypatch):
        import agents.verifier as module
        state, board, logger = context
        (Path(state.workspace_path) / 'test_failure.py').write_text('def test_failure():\n    assert False\n')
        agent = agent_instance(module, 'VerifierAgent', context, monkeypatch)
        agent._dispatch('run_command', {'command': 'python -m pytest -q test_failure.py -p no:cacheprovider'})
        agent._dispatch('run_command', {'command': 'ls'})
        assert state.test_runs[0].exit_code == 1
        orch = Orchestrator.__new__(Orchestrator)
        orch.state = state
>       assert orch._failed_tests()
E       assert False
E        +  where False = _failed_tests()
E        +    where _failed_tests = <core.orchestrator.Orchestrator object at 0x10afa6ba0>._failed_tests

test_siddharth_regressions.py:137: AssertionError
____________________ test_approval_rejects_unmet_criterion _____________________

context = (SharedState(run_id='review', request='Implement the requested small change', repo_path='/private/var/folders/kr/jqmy8..., last_verify_time=''), <core.board.MessageBoard object at 0x10afe6e50>, <core.logger.RunLogger object at 0x10afe6c50>)
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x10af7fe30>

    def test_approval_rejects_unmet_criterion(context, monkeypatch):
        import agents.planner as planner_module
        state, board, logger = context
        state.criteria.append(Criterion('c1', 'Not verified', CriterionStatus.UNMET))
        state.tasks.append(Task('t1', 'Completed fixture task', 'developer', TaskStatus.DONE))
        from core.state import TestRun
        state.test_runs.append(TestRun('synthetic precondition: green suite', 0, 'mocked', '2099-01-01'))
        orch = Orchestrator.__new__(Orchestrator)
        orch.run_id = state.run_id
        orch.workspace_path = Path(state.workspace_path)
        orch.state, orch.board, orch.logger = state, board, logger
        orch._step_count, orch._max_global_steps = 0, 3
        monkeypatch.setattr(planner_module, 'PlannerAgent', lambda *args: SimpleNamespace(run=lambda: True))
        monkeypatch.setattr(orch, '_review_done', lambda: True)
        approval = Mock()
        monkeypatch.setattr(orch, '_request_human_approval', approval)
        orch.run()
>       approval.assert_not_called()

test_siddharth_regressions.py:157: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

self = <Mock id='4479150000'>

    def assert_not_called(self):
        """assert that the mock was never called.
        """
        if self.call_count != 0:
            msg = ("Expected '%s' to not have been called. Called %s times.%s"
                   % (self._mock_name or 'mock',
                      self.call_count,
                      self._calls_repr()))
>           raise AssertionError(msg)
E           AssertionError: Expected 'mock' to not have been called. Called 1 times.
E           Calls: [call()].

<python-install>/lib/python3.14/unittest/mock.py:947: AssertionError
----------------------------- Captured stdout call -----------------------------

🚀 DevPilot Run: review
📁 Workspace: <pytest-temp>/pytest-11/test_approval_rejects_unmet_cr0/workspace
📝 Request: Implement the requested small change

📋 Plan: 1 criteria, 1 tasks

✅ All checks passed. Requesting human approval...
________________ test_apply_preserves_unmodified_original_files ________________

context = (SharedState(run_id='review', request='Implement the requested small change', repo_path='/private/var/folders/kr/jqmy8..., last_verify_time=''), <core.board.MessageBoard object at 0x10afe5d50>, <core.logger.RunLogger object at 0x10afe5650>)

    def test_apply_preserves_unmodified_original_files(context):
        state, board, logger = context
        original = Path(state.repo_path)
        workspace = Path(state.workspace_path)
        (original / 'unchanged.txt').write_text('new user edit made during mission')
        (workspace / 'unchanged.txt').write_text('old imported content')
        (workspace / 'changed.txt').write_text('approved change')
        orch = Orchestrator.__new__(Orchestrator)
        orch.state, orch.workspace_path, orch.logger = state, workspace, logger
        orch._apply_changes()
>       assert (original / 'unchanged.txt').read_text() == 'new user edit made during mission'
E       AssertionError: assert 'old imported content' == 'new user edi...uring mission'
E         
E         - new user edit made during mission
E         + old imported content

test_siddharth_regressions.py:170: AssertionError
_____________ test_old_finding_does_not_force_repair_after_success _____________

context = (SharedState(run_id='review', request='Implement the requested small change', repo_path='/private/var/folders/kr/jqmy8..., last_verify_time=''), <core.board.MessageBoard object at 0x10af7dc70>, <core.logger.RunLogger object at 0x10af7d400>)

    def test_old_finding_does_not_force_repair_after_success(context):
        state, board, logger = context
        state.criteria.append(Criterion('c1', 'Now verified', CriterionStatus.MET))
        board.post('VERIFY_FINDING', 'verifier', 'developer', {'criterion_id': 'c1'})
        orch = Orchestrator.__new__(Orchestrator)
        orch.state, orch.board = state, board
>       assert not orch._unmet_criteria()
E       assert not True
E        +  where True = _unmet_criteria()
E        +    where _unmet_criteria = <core.orchestrator.Orchestrator object at 0x10aebf950>._unmet_criteria

test_siddharth_regressions.py:179: AssertionError
______________ test_planner_uses_clarification_answer_to_continue ______________

context = (SharedState(run_id='review', request='Implement the requested small change', repo_path='/private/var/folders/kr/jqmy8..., last_verify_time=''), <core.board.MessageBoard object at 0x10b51e3f0>, <core.logger.RunLogger object at 0x10b51e030>)
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x10afc6a90>

    def test_planner_uses_clarification_answer_to_continue(context, monkeypatch):
        import agents.planner as module
        agent = agent_instance(module, 'PlannerAgent', context, monkeypatch)
        monkeypatch.setattr('builtins.input', lambda prompt: 'SAVE10 gives ten percent off')
    
        def simulated_loop(**kwargs):
            kwargs['dispatch_fn']('clarify', {'question': 'What coupon should be added?'})
            if not kwargs['stop_check']():
                kwargs['dispatch_fn']('set_plan', {'criteria': [{'id': 'c1', 'text': 'SAVE10 discount works'}], 'tasks': [{'id': 't1', 'text': 'Add coupon'}]})
            return 'Answered'
    
        monkeypatch.setattr(module, 'run_agent_loop', simulated_loop)
>       assert agent.run()
E       assert False
E        +  where False = run()
E        +    where run = <agents.planner.PlannerAgent object at 0x10afa5940>.run

test_siddharth_regressions.py:194: AssertionError
----------------------------- Captured stdout call -----------------------------

🤔 CLARIFY: What coupon should be added?
____________________ test_scenario_outcome_uses_enum_value _____________________

    def test_scenario_outcome_uses_enum_value():
>       assert str(RunStatus.ESCALATED) == 'escalated'
E       AssertionError: assert 'RunStatus.ESCALATED' == 'escalated'
E         
E         - escalated
E         + RunStatus.ESCALATED

test_siddharth_regressions.py:198: AssertionError
____________ test_tool_result_is_sent_back_after_stop_function_call ____________

    def test_tool_result_is_sent_back_after_stop_function_call():
        """A mocked Gemini tool-call turn still needs a subsequent model round trip."""
        from google.genai import types
        from core.gemini_client import run_agent_loop
        first = SimpleNamespace(candidates=[SimpleNamespace(
            content=types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(name="read_file", args={"path": "fixture.py"}))]),
            finish_reason=types.FinishReason.STOP,
        )])
        second = SimpleNamespace(candidates=[SimpleNamespace(
            content=types.Content(role="model", parts=[types.Part(text="Used the fixture output")]),
            finish_reason=types.FinishReason.STOP,
        )])
        client = SimpleNamespace(models=SimpleNamespace(generate_content=Mock(side_effect=[first, second])))
        dispatch = Mock(return_value="synthetic fixture output")
        result = run_agent_loop(client=client, model="fixture-model", system_prompt="Fixture test", tools_config=[], initial_message="Read then explain fixture", dispatch_fn=dispatch, max_iterations=3)
>       assert client.models.generate_content.call_count == 2, {"calls": client.models.generate_content.call_count, "final_text": result}
E       AssertionError: {'calls': 1, 'final_text': ''}
E       assert 1 == 2
E        +  where 1 = <Mock id='4513445408'>.call_count
E        +    where <Mock id='4513445408'> = namespace(generate_content=<Mock id='4513445408'>).generate_content
E        +      where namespace(generate_content=<Mock id='4513445408'>) = namespace(models=namespace(generate_content=<Mock id='4513445408'>)).models

test_siddharth_regressions.py:216: AssertionError
=========================== short test summary info ============================
FAILED test_siddharth_regressions.py::test_workspace_prefix_sibling_is_rejected
FAILED test_siddharth_regressions.py::test_file_tool_denies_dotenv - Failed: ...
FAILED test_siddharth_regressions.py::test_search_rejects_symlink_to_outside
FAILED test_siddharth_regressions.py::test_command_rejects_shell_separator - ...
FAILED test_siddharth_regressions.py::test_command_rejects_outside_file_argument
FAILED test_siddharth_regressions.py::test_developer_finishing_updates_task
FAILED test_siddharth_regressions.py::test_developer_retains_budget_after_short_run
FAILED test_siddharth_regressions.py::test_verifier_can_mark_passing_criterion
FAILED test_siddharth_regressions.py::test_failing_suite_is_not_hidden_by_later_ls
FAILED test_siddharth_regressions.py::test_approval_rejects_unmet_criterion
FAILED test_siddharth_regressions.py::test_apply_preserves_unmodified_original_files
FAILED test_siddharth_regressions.py::test_old_finding_does_not_force_repair_after_success
FAILED test_siddharth_regressions.py::test_planner_uses_clarification_answer_to_continue
FAILED test_siddharth_regressions.py::test_scenario_outcome_uses_enum_value
FAILED test_siddharth_regressions.py::test_tool_result_is_sent_back_after_stop_function_call
15 failed in 0.41s
```

## dashboard-check

Started UTC: `2026-10-29T22:00:44.677990+00:00`. Exit code: `0`.

Command and working directory:

```text
{
  "command": [
    "<review-venv>/bin/python",
    "-c",
    "import json\nfrom streamlit.testing.v1 import AppTest\nat=AppTest.from_file(\"<isolated-review>/devpilot/dashboard/app.py\",default_timeout=5).run()\nresult={\"start_page_exceptions\":len(at.exception)}\ntry:\n    at.radio[0].set_value(\"\ud83d\udce1 Live View\").run()\n    result[\"live_view\"]=\"finished\"\nexcept Exception as e:\n    result[\"live_view_error\"]=type(e).__name__+\": \"+str(e)\nprint(json.dumps(result))\n"
  ],
  "cwd": "<review-home>/Documents/pecathon/branch-reviews"
}
```

Standard output:

```text
{"start_page_exceptions": 0, "live_view_error": "RuntimeError: AppTest script run timed out after 5(s)"}
```

Standard error:

```text
2026-10-30 03:30:44.849 WARNING streamlit.runtime.scriptrunner_utils.script_run_context: Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
```

## Prior demo validation

This preserves the previously captured demo-fixture output. Seeded failures are expected test inputs; a random stuck-fixture result is not proof of retry-limit escalation.

```json
[
  {
    "repo": "bugfix_repo",
    "command": [
      "<review-venv>/bin/python",
      "-m",
      "pytest",
      "-q",
      "-p",
      "no:cacheprovider"
    ],
    "exit_code": 1,
    "stdout": "FF.                                                                      [100%]\n=================================== FAILURES ===================================\n________________________________ test_get_top_3 ________________________________\n\n    def test_get_top_3():\n        \"\"\"get_top_n(items, 3) should return exactly 3 items.\"\"\"\n        result = get_top_n([5, 2, 8, 1, 9, 3], 3)\n>       assert len(result) == 3, f\"Expected 3 items, got {len(result)}: {result}\"\nE       AssertionError: Expected 3 items, got 4: [9, 8, 5, 3]\nE       assert 4 == 3\nE        +  where 4 = len([9, 8, 5, 3])\n\ntests/test_utils.py:13: AssertionError\n____________________________ test_get_top_n_values _____________________________\n\n    def test_get_top_n_values():\n        \"\"\"Top 3 from [5,2,8,1,9,3] should be [9,8,5].\"\"\"\n        result = get_top_n([5, 2, 8, 1, 9, 3], 3)\n>       assert result == [9, 8, 5], f\"Got: {result}\"\nE       AssertionError: Got: [9, 8, 5, 3]\nE       assert [9, 8, 5, 3] == [9, 8, 5]\nE         \nE         Left contains one more item: 3\nE         Use -v to get more diff\n\ntests/test_utils.py:19: AssertionError\n=========================== short test summary info ============================\nFAILED tests/test_utils.py::test_get_top_3 - AssertionError: Expected 3 items...\nFAILED tests/test_utils.py::test_get_top_n_values - AssertionError: Got: [9, ...\n2 failed, 1 passed in 0.01s\n",
    "stderr": ""
  },
  {
    "repo": "failing_test_repo",
    "command": [
      "<review-venv>/bin/python",
      "-m",
      "pytest",
      "-q",
      "-p",
      "no:cacheprovider"
    ],
    "exit_code": 2,
    "stdout": "\n==================================== ERRORS ====================================\n____________________ ERROR collecting tests/test_greeter.py ____________________\nImportError while importing test module '<isolated-review>/devpilot/demo_repos/failing_test_repo/tests/test_greeter.py'.\nHint: make sure your test modules/packages have valid Python names.\nTraceback:\n<python-install>/lib/python3.14/importlib/__init__.py:88: in import_module\n    return _bootstrap._gcd_import(name[level:], package, level)\n           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\ntests/test_greeter.py:9: in <module>\n    from greeter import say_hello\nE   ImportError: cannot import name 'say_hello' from 'greeter' (<isolated-review>/devpilot/demo_repos/failing_test_repo/greeter.py)\n=========================== short test summary info ============================\nERROR tests/test_greeter.py\n!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!\n1 error in 0.03s\n",
    "stderr": ""
  },
  {
    "repo": "security_repo",
    "command": [
      "<review-venv>/bin/python",
      "-m",
      "pytest",
      "-q",
      "-p",
      "no:cacheprovider"
    ],
    "exit_code": 0,
    "stdout": "..                                                                       [100%]\n2 passed in 0.00s\n",
    "stderr": ""
  },
  {
    "repo": "notools_repo",
    "command": [
      "<review-venv>/bin/python",
      "-m",
      "pytest",
      "-q",
      "-p",
      "no:cacheprovider"
    ],
    "exit_code": 0,
    "stdout": "...                                                                      [100%]\n3 passed in 0.00s\n",
    "stderr": ""
  },
  {
    "repo": "stuck_repo",
    "command": [
      "<review-venv>/bin/python",
      "-m",
      "pytest",
      "-q",
      "-p",
      "no:cacheprovider"
    ],
    "exit_code": 1,
    "stdout": "F                                                                        [100%]\n=================================== FAILURES ===================================\n_____________________________ test_compute_answer ______________________________\n\n    def test_compute_answer():\n        \"\"\"compute_answer must return exactly 42.\"\"\"\n        result = compute_answer()\n        # This is intentionally hard to fix without understanding the domain\n>       assert result == 42, f\"Expected 42, got {result}\"\nE       AssertionError: Expected 42, got 95\nE       assert 95 == 42\n\ntests/test_solver.py:14: AssertionError\n=========================== short test summary info ============================\nFAILED tests/test_solver.py::test_compute_answer - AssertionError: Expected 4...\n1 failed in 0.01s\n",
    "stderr": ""
  }
]
```

## Review regression source

Save the following source as `docs/reviews/test_review_regressions.py` to reproduce the review checks against the repository. Install `devpilot/requirements.txt` into a virtual environment and run `python -m pytest docs/reviews/test_review_regressions.py -q` with that environment active. The checks are expected to fail at the reviewed commit.

```python
"""Independent review checks; model calls are mocked, filesystem operations are real."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'devpilot'))

from core.state import SharedState, Criterion, CriterionStatus, Task, TaskStatus, ReviewIssue, RunStatus
from core.board import MessageBoard
from core.logger import RunLogger
from core.orchestrator import Orchestrator
from tools.safety import SafetyError
from tools.file_tools import read_file, search_code
from tools.command_tool import run_command


@pytest.fixture
def context(tmp_path, monkeypatch):
    import core.logger
    workspace = tmp_path / 'workspace'
    original = tmp_path / 'original'
    logs = tmp_path / 'logs'
    for directory in (workspace, original, logs):
        directory.mkdir()
    monkeypatch.setattr(core.logger, 'RUNS_DIR', logs)
    state = SharedState('review', 'Implement the requested small change', str(original), str(workspace))
    return state, MessageBoard(), RunLogger('review')


def agent_instance(module, name, context, monkeypatch):
    monkeypatch.setattr(module, 'make_client', lambda: None)
    return getattr(module, name)(*context)


def test_workspace_prefix_sibling_is_rejected(tmp_path):
    workspace = tmp_path / 'workspace'
    sibling = tmp_path / 'workspace_other'
    workspace.mkdir()
    sibling.mkdir()
    marker = sibling / 'marker.txt'
    marker.write_text('synthetic outside marker')
    with pytest.raises(SafetyError):
        read_file(str(marker), str(workspace))


def test_file_tool_denies_dotenv(context):
    state, _, _ = context
    target = Path(state.workspace_path) / '.env'
    target.write_text('REVIEW_MARKER=synthetic_value')
    with pytest.raises(SafetyError):
        read_file(str(target), state.workspace_path)


def test_search_rejects_symlink_to_outside(context):
    state, _, _ = context
    marker = Path(state.repo_path) / 'outside.py'
    marker.write_text('review_outside_marker = True')
    (Path(state.workspace_path) / 'alias.py').symlink_to(marker)
    assert search_code('review_outside_marker', state.workspace_path) == []


def test_command_rejects_shell_separator(context):
    state, _, _ = context
    result = run_command('ls ; printf review_shell_marker', state.workspace_path)
    assert result['blocked'], result


def test_command_rejects_outside_file_argument(context):
    state, _, _ = context
    marker = Path(state.repo_path) / 'marker.txt'
    marker.write_text('synthetic outside marker')
    result = run_command(f'cat {marker}', state.workspace_path)
    assert result['blocked'], result


def test_developer_finishing_updates_task(context, monkeypatch):
    import agents.developer as module
    state, _, _ = context
    state.tasks.append(Task('t1', 'Create answer module', 'developer'))
    agent = agent_instance(module, 'DeveloperAgent', context, monkeypatch)

    def simulated_loop(**kwargs):
        kwargs['dispatch_fn']('edit_file', {'path': 'answer.py', 'content': 'answer = 42\n'})
        return 'Completed task t1'

    monkeypatch.setattr(module, 'run_agent_loop', simulated_loop)
    agent.run()
    assert state.tasks[0].status == TaskStatus.DONE


def test_developer_retains_budget_after_short_run(context, monkeypatch):
    import agents.developer as module
    state, _, _ = context
    budgets = []

    def simulated_one_iteration(**kwargs):
        budgets.append(kwargs['max_iterations'])
        return 'One simulated model response'

    monkeypatch.setattr(module, 'run_agent_loop', simulated_one_iteration)
    agent_instance(module, 'DeveloperAgent', context, monkeypatch).run()
    agent_instance(module, 'DeveloperAgent', context, monkeypatch).run()
    assert budgets[1] > 0, budgets


def test_verifier_can_mark_passing_criterion(context, monkeypatch):
    import agents.verifier as module
    state, _, _ = context
    state.criteria.append(Criterion('c1', 'Independent arithmetic check succeeds'))
    (Path(state.workspace_path) / 'probe.py').write_text('assert 2 + 2 == 4\n')
    agent = agent_instance(module, 'VerifierAgent', context, monkeypatch)

    def simulated_loop(**kwargs):
        output = kwargs['dispatch_fn']('run_command', {'command': 'python probe.py'})
        assert 'exit_code=0' in output
        return 'Criterion c1 passed with independent probe evidence'

    monkeypatch.setattr(module, 'run_agent_loop', simulated_loop)
    agent.run()
    assert state.criteria[0].status == CriterionStatus.MET


def test_failing_suite_is_not_hidden_by_later_ls(context, monkeypatch):
    import agents.verifier as module
    state, board, logger = context
    (Path(state.workspace_path) / 'test_failure.py').write_text('def test_failure():\n    assert False\n')
    agent = agent_instance(module, 'VerifierAgent', context, monkeypatch)
    agent._dispatch('run_command', {'command': 'python -m pytest -q test_failure.py -p no:cacheprovider'})
    agent._dispatch('run_command', {'command': 'ls'})
    assert state.test_runs[0].exit_code == 1
    orch = Orchestrator.__new__(Orchestrator)
    orch.state = state
    assert orch._failed_tests()


def test_approval_rejects_unmet_criterion(context, monkeypatch):
    import agents.planner as planner_module
    state, board, logger = context
    state.criteria.append(Criterion('c1', 'Not verified', CriterionStatus.UNMET))
    state.tasks.append(Task('t1', 'Completed fixture task', 'developer', TaskStatus.DONE))
    from core.state import TestRun
    state.test_runs.append(TestRun('synthetic precondition: green suite', 0, 'mocked', '2099-01-01'))
    orch = Orchestrator.__new__(Orchestrator)
    orch.run_id = state.run_id
    orch.workspace_path = Path(state.workspace_path)
    orch.state, orch.board, orch.logger = state, board, logger
    orch._step_count, orch._max_global_steps = 0, 3
    monkeypatch.setattr(planner_module, 'PlannerAgent', lambda *args: SimpleNamespace(run=lambda: True))
    monkeypatch.setattr(orch, '_review_done', lambda: True)
    approval = Mock()
    monkeypatch.setattr(orch, '_request_human_approval', approval)
    orch.run()
    approval.assert_not_called()


def test_apply_preserves_unmodified_original_files(context):
    state, board, logger = context
    original = Path(state.repo_path)
    workspace = Path(state.workspace_path)
    (original / 'unchanged.txt').write_text('new user edit made during mission')
    (workspace / 'unchanged.txt').write_text('old imported content')
    (workspace / 'changed.txt').write_text('approved change')
    orch = Orchestrator.__new__(Orchestrator)
    orch.state, orch.workspace_path, orch.logger = state, workspace, logger
    orch._apply_changes()
    assert (original / 'unchanged.txt').read_text() == 'new user edit made during mission'


def test_old_finding_does_not_force_repair_after_success(context):
    state, board, logger = context
    state.criteria.append(Criterion('c1', 'Now verified', CriterionStatus.MET))
    board.post('VERIFY_FINDING', 'verifier', 'developer', {'criterion_id': 'c1'})
    orch = Orchestrator.__new__(Orchestrator)
    orch.state, orch.board = state, board
    assert not orch._unmet_criteria()


def test_planner_uses_clarification_answer_to_continue(context, monkeypatch):
    import agents.planner as module
    agent = agent_instance(module, 'PlannerAgent', context, monkeypatch)
    monkeypatch.setattr('builtins.input', lambda prompt: 'SAVE10 gives ten percent off')

    def simulated_loop(**kwargs):
        kwargs['dispatch_fn']('clarify', {'question': 'What coupon should be added?'})
        if not kwargs['stop_check']():
            kwargs['dispatch_fn']('set_plan', {'criteria': [{'id': 'c1', 'text': 'SAVE10 discount works'}], 'tasks': [{'id': 't1', 'text': 'Add coupon'}]})
        return 'Answered'

    monkeypatch.setattr(module, 'run_agent_loop', simulated_loop)
    assert agent.run()


def test_scenario_outcome_uses_enum_value():
    assert str(RunStatus.ESCALATED) == 'escalated'


def test_tool_result_is_sent_back_after_stop_function_call():
    """A mocked Gemini tool-call turn still needs a subsequent model round trip."""
    from google.genai import types
    from core.gemini_client import run_agent_loop
    first = SimpleNamespace(candidates=[SimpleNamespace(
        content=types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(name="read_file", args={"path": "fixture.py"}))]),
        finish_reason=types.FinishReason.STOP,
    )])
    second = SimpleNamespace(candidates=[SimpleNamespace(
        content=types.Content(role="model", parts=[types.Part(text="Used the fixture output")]),
        finish_reason=types.FinishReason.STOP,
    )])
    client = SimpleNamespace(models=SimpleNamespace(generate_content=Mock(side_effect=[first, second])))
    dispatch = Mock(return_value="synthetic fixture output")
    result = run_agent_loop(client=client, model="fixture-model", system_prompt="Fixture test", tools_config=[], initial_message="Read then explain fixture", dispatch_fn=dispatch, max_iterations=3)
    assert client.models.generate_content.call_count == 2, {"calls": client.models.generate_content.call_count, "final_text": result}
    assert result == "Used the fixture output"
```
