import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from promptflow._core._errors import PackageToolNotFoundError, ToolLoadError
from promptflow.contracts.run_info import Status
from promptflow.executor import FlowExecutor
from promptflow.executor._errors import NodeInputValidationError, ResolveToolError
from promptflow.executor._result import LineResult

from ..utils import WRONG_FLOW_ROOT, get_flow_package_tool_definition, get_flow_sample_inputs, get_yaml_file

PACKAGE_TOOL_BASE = Path(__file__).parent.parent / "package_tools"
PACKAGE_TOOL_ENTRY = "promptflow._core.tools_manager.collect_package_tools"

sys.path.insert(0, str(PACKAGE_TOOL_BASE.resolve()))


@pytest.mark.e2etest
class TestPackageTool:
    def get_line_inputs(self, flow_folder=""):
        if flow_folder:
            inputs = self.get_bulk_inputs(flow_folder)
            return inputs[0]
        return {
            "url": "https://www.apple.com/shop/buy-iphone/iphone-14",
            "text": "some_text",
        }

    def get_bulk_inputs(self, nlinee=4, flow_folder=""):
        if flow_folder:
            inputs = get_flow_sample_inputs(flow_folder)
            if isinstance(inputs, list) and len(inputs) > 0:
                return inputs
            elif isinstance(inputs, dict):
                return [inputs]
            else:
                raise Exception(f"Invalid type of bulk input: {inputs}")
        return [self.get_line_inputs() for _ in range(nlinee)]

    def test_executor_package_tool_with_conn(self, mocker):
        flow_folder = PACKAGE_TOOL_BASE / "tool_with_connection"
        package_tool_definition = get_flow_package_tool_definition(flow_folder)
        mocker.patch(
            "promptflow.tools.list.list_package_tools",
            return_value=package_tool_definition,
        )
        name, secret = "dummy_name", "dummy_secret"
        connections = {
            "test_conn": {
                "type": "TestConnection",
                "value": {"name": name, "secret": secret},
            }
        }
        executor = FlowExecutor.create(get_yaml_file(flow_folder), connections, raise_ex=True)
        flow_result = executor.exec_line({})
        assert flow_result.run_info.status == Status.Completed
        assert len(flow_result.node_run_infos) == 1
        for _, v in flow_result.node_run_infos.items():
            assert v.status == Status.Completed
            assert v.output == name + secret

    @pytest.mark.skipif(sys.platform == "darwin", reason="Skip on Mac")
    def test_executor_package_with_prompt_tool(self, dev_connections, mocker):
        flow_folder = PACKAGE_TOOL_BASE / "custom_llm_tool"
        package_tool_definition = get_flow_package_tool_definition(flow_folder)
        with mocker.patch(PACKAGE_TOOL_ENTRY, return_value=package_tool_definition):
            executor = FlowExecutor.create(get_yaml_file(flow_folder), dev_connections, raise_ex=True)
            bulk_inputs = self.get_bulk_inputs(flow_folder=flow_folder)
            for i in bulk_inputs:
                line_result = executor.exec_line(i)
                assert isinstance(line_result, LineResult)
                msg = f"Got {line_result.run_info.status} for input {i}"
                assert line_result.run_info.status == Status.Completed, msg

    def test_custom_llm_tool_with_duplicated_inputs(self, dev_connections, mocker):
        flow_folder = PACKAGE_TOOL_BASE / "custom_llm_tool_with_duplicated_inputs"
        package_tool_definition = get_flow_package_tool_definition(flow_folder)
        with mocker.patch(PACKAGE_TOOL_ENTRY, return_value=package_tool_definition):
            msg = (
                "Invalid inputs {'api'} in prompt template of node custom_llm_tool_with_duplicated_inputs. "
                "These inputs are duplicated with the inputs of custom llm tool."
            )
            with pytest.raises(ResolveToolError, match=msg) as e:
                FlowExecutor.create(get_yaml_file(flow_folder), dev_connections)
            assert isinstance(e.value.inner_exception, NodeInputValidationError)

    @pytest.mark.parametrize(
        "flow_folder, error_class, inner_class, error_message",
        [
            (
                "wrong_tool_in_package_tools",
                ResolveToolError,
                PackageToolNotFoundError,
                "Tool load failed in 'search_by_text': (PackageToolNotFoundError) "
                "Package tool 'promptflow.tools.serpapi.SerpAPI.search_11' is not found in the current environment. "
                "All available package tools are: "
                "['promptflow.tools.azure_content_safety.AzureContentSafety.analyze_text', "
                "'promptflow.tools.azure_detect.AzureDetect.get_language'].",
            ),
            (
                "wrong_package_in_package_tools",
                ResolveToolError,
                PackageToolNotFoundError,
                "Tool load failed in 'search_by_text': (PackageToolNotFoundError) "
                "Package tool 'promptflow.tools.serpapi11.SerpAPI.search' is not found in the current environment. "
                "All available package tools are: "
                "['promptflow.tools.azure_content_safety.AzureContentSafety.analyze_text', "
                "'promptflow.tools.azure_detect.AzureDetect.get_language'].",
            ),
        ],
    )
    def test_package_tool_execution(self, flow_folder, error_class, inner_class, error_message, dev_connections):
        def mock_collect_package_tools(keys=None):
            return {
                "promptflow.tools.azure_content_safety.AzureContentSafety.analyze_text": None,
                "promptflow.tools.azure_detect.AzureDetect.get_language": None,
            }

        with patch(PACKAGE_TOOL_ENTRY, side_effect=mock_collect_package_tools):
            with pytest.raises(error_class) as exce_info:
                FlowExecutor.create(get_yaml_file(flow_folder, WRONG_FLOW_ROOT), dev_connections)
            if isinstance(exce_info.value, ResolveToolError):
                assert isinstance(exce_info.value.inner_exception, inner_class)
            assert error_message == exce_info.value.message

    @pytest.mark.parametrize(
        "flow_folder, error_message",
        [
            (
                "tool_with_init_error",
                "Tool load failed in 'tool_with_init_error': "
                "(ToolLoadError) Failed to load package tool 'Tool with init error': (Exception) Tool load error.",
            )
        ],
    )
    def test_package_tool_load_error(self, flow_folder, error_message, dev_connections, mocker):
        flow_folder = PACKAGE_TOOL_BASE / flow_folder
        package_tool_definition = get_flow_package_tool_definition(flow_folder)
        with mocker.patch(PACKAGE_TOOL_ENTRY, return_value=package_tool_definition):
            with pytest.raises(ResolveToolError) as exce_info:
                FlowExecutor.create(get_yaml_file(flow_folder), dev_connections)
            assert isinstance(exce_info.value.inner_exception, ToolLoadError)
            assert exce_info.value.message == error_message
