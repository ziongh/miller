# The Complete Guide to AI Agent Behavioral Adoption
## How Serena Gets Agents to Use Its Tools Instead of Built-in Ones

This guide documents **every technique** Serena uses to achieve unprecedented "buy-in" from AI agents, making them preferentially use Serena's MCP tools over their own built-in capabilities.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [The Complete Initialization Flow](#the-complete-initialization-flow)
3. [Layer-by-Layer Injection Points](#layer-by-layer-injection-points)
4. [Tool Exclusion Mechanisms](#tool-exclusion-mechanisms)
5. [Prompt Engineering Techniques](#prompt-engineering-techniques)
6. [Agent Mode Configuration](#agent-mode-configuration)
7. [Replication Checklist](#replication-checklist)
8. [Real Examples from Serena](#real-examples-from-serena)

---

## Architecture Overview

### The Instruction Stack

Serena uses a **four-layer instruction system** where each layer reinforces the previous one:

```
Layer 1: Base System Prompt (system_prompt.yml)
    ↓ Injected via MCP server.instructions
Layer 2: Context Prompt (contexts/agent.yml)
    ↓ Rendered into system prompt via Jinja2
Layer 3: Mode Prompts (modes/editing.yml, modes/interactive.yml)
    ↓ Rendered into system prompt via Jinja2
Layer 4: Tool Descriptions (in tool docstrings)
    ↓ Injected via MCP tool schema
```

**Key Insight**: Every layer contains directive, emotional, and behavioral instructions. By the time an agent sees a tool, it has been "programmed" 4 times to use it correctly.

---

## The Complete Initialization Flow

### 1. Entry Point: MCP Server Startup

**File**: `scripts/mcp_server.py` (or equivalent)
```python
from serena.cli import start_mcp_server

if __name__ == "__main__":
    start_mcp_server()
```

**CLI Command Definition**: `cli.py:141-192`
```python
@click.command("start-mcp-server")
@click.option("--context", type=str,
              default=DEFAULT_CONTEXT,  # "desktop-app" or "agent"
              help="Built-in context name or path to custom context YAML.")
@click.option("--mode", "modes", type=str, multiple=True,
              default=DEFAULT_MODES,  # ("interactive", "editing")
              help="Built-in mode names or paths to custom mode YAMLs.")
def start_mcp_server(context: str, modes: tuple[str, ...], ...):
    # Creates factory with YAML names/paths
    factory = SerenaMCPFactorySingleProcess(
        context=context,
        project=project_file,
        memory_log_handler=memory_log_handler
    )

    # Creates server with loaded YAMLs
    server = factory.create_mcp_server(
        modes=modes,
        ...
    )

    server.run(transport=transport)
```

**Constants**: `constants.py:29-30`
```python
DEFAULT_CONTEXT = "desktop-app"  # Or "agent" for MCP
DEFAULT_MODES = ("interactive", "editing")
```

---

### 2. YAML Loading: Contexts and Modes

**Factory Initialization**: `mcp.py:50-58`
```python
class SerenaMCPFactory:
    def __init__(self, context: str = DEFAULT_CONTEXT, project: str | None = None):
        # CRITICAL: Context YAML loaded here
        self.context = SerenaAgentContext.load(context)
        self.project = project
```

**Context Loading Logic**: `config/context_mode.py:173-176`
```python
@classmethod
def load(cls, name_or_path: str | Path) -> Self:
    if str(name_or_path).endswith(".yml"):
        return cls.from_yaml(name_or_path)  # Custom path
    return cls.from_name(str(name_or_path))  # Built-in name

@classmethod
def get_path(cls, name: str) -> str:
    fname = f"{name}.yml"

    # Check user override FIRST
    custom_path = os.path.join(USER_CONTEXT_YAMLS_DIR, fname)
    if os.path.exists(custom_path):
        return custom_path  # ~/.serena/contexts/agent.yml

    # Fall back to built-in
    builtin_path = os.path.join(SERENAS_OWN_CONTEXT_YAMLS_DIR, fname)
    return builtin_path  # src/serena/resources/config/contexts/agent.yml
```

**Same logic applies to Modes**: `SerenaAgentMode.load()` follows identical pattern

**YAML Structure**:
```yaml
# contexts/agent.yml
description: All tools except InitialInstructionsTool for agent context
prompt: |
  You are running in agent context where the system prompt is provided externally.
  You should use symbolic tools when possible for code understanding and modification.
excluded_tools:
  - initial_instructions
tool_description_overrides: {}
```

```yaml
# modes/editing.yml
description: All tools, with detailed instructions for code editing
prompt: |
  You are operating in editing mode. You can edit files...
  [100+ lines of detailed instructions]
excluded_tools:
  - replace_lines
  - insert_at_line
  - delete_lines
```

---

### 3. Agent Creation and Prompt Assembly

**MCP Server Creation**: `mcp.py:246-300`
```python
def create_mcp_server(self, modes: Sequence[str] = DEFAULT_MODES, ...):
    config = SerenaConfig.from_config_file()

    # Load mode YAMLs into objects
    modes_instances = [SerenaAgentMode.load(mode) for mode in modes]

    # Create agent with context + modes
    self._instantiate_agent(config, modes_instances)

    # Generate complete system prompt
    instructions = self._get_initial_instructions()

    # Pass to MCP (THE CRITICAL INJECTION POINT)
    mcp = FastMCP(instructions=instructions, ...)
    return mcp
```

**Agent Instantiation**: `mcp.py:329-332`
```python
def _instantiate_agent(self, serena_config, modes):
    self.agent = SerenaAgent(
        project=self.project,
        serena_config=serena_config,
        context=self.context,  # Loaded context object
        modes=modes,           # List of loaded mode objects
        ...
    )
```

**Prompt Generation**: `agent.py:371-381`
```python
def create_system_prompt(self) -> str:
    available_markers = self._exposed_tools.tool_marker_names

    system_prompt = self.prompt_factory.create_system_prompt(
        context_system_prompt=self._format_prompt(self._context.prompt),
        mode_system_prompts=[self._format_prompt(mode.prompt) for mode in self._modes],
        available_tools=self._exposed_tools.tool_names,
        available_markers=available_markers,
    )
    return system_prompt
```

**Jinja2 Rendering**: `generated_prompt_factory.py:35-38`
```python
def create_system_prompt(
    self, *, available_markers: Any, available_tools: Any,
    context_system_prompt: Any, mode_system_prompts: Any
) -> str:
    return self._render_prompt("system_prompt", locals())
```

**Template**: `prompt_templates/system_prompt.yml:5-67`
```yaml
prompts:
  system_prompt: |
    You are a professional coding agent concerned with one particular codebase...

    I WILL BE SERIOUSLY UPSET IF YOU READ ENTIRE FILES WITHOUT NEED!
    CONSIDER INSTEAD USING THE OVERVIEW TOOL AND SYMBOLIC TOOLS...

    Context description:
    {{ context_system_prompt }}

    Modes descriptions:
    {% for prompt in mode_system_prompts %}
    - {{ prompt }}
    {% endfor %}
```

---

### 4. MCP Injection

**Final Assembly**: `mcp.py:338-341` → `mcp.py:298-300`
```python
def _get_initial_instructions(self) -> str:
    return self.agent.create_system_prompt()

# Then:
instructions = self._get_initial_instructions()
mcp = FastMCP(
    lifespan=self.server_lifespan,
    host=host,
    port=port,
    instructions=instructions  # ← THE MAGIC PARAMETER
)
```

**What Happens in MCP**: The `instructions` field is part of the **standard MCP protocol**. When the agent connects, it receives:

```json
{
  "serverInfo": {
    "name": "serena-mcp-server",
    "version": "1.0.0",
    "instructions": "<FULL SYSTEM PROMPT TEXT>"
  }
}
```

This gets injected into the agent's system context automatically.

---

## Layer-by-Layer Injection Points

### Layer 1: Base System Prompt

**File**: `prompt_templates/system_prompt.yml`

**When Loaded**: During `PromptFactory.__init__()` at agent creation

**Where Injected**: MCP `server.instructions`

**Key Techniques**:
- Emotional appeals ("I WILL BE SERIOUSLY UPSET")
- ALL CAPS directives
- Repeated emphasis
- Specific workflows

**Example**:
```yaml
I WILL BE SERIOUSLY UPSET IF YOU READ ENTIRE FILES WITHOUT NEED!

CONSIDER INSTEAD USING THE OVERVIEW TOOL AND SYMBOLIC TOOLS TO READ ONLY THE NECESSARY CODE FIRST!
I WILL BE EVEN MORE UPSET IF AFTER HAVING READ AN ENTIRE FILE YOU KEEP READING THE SAME CONTENT WITH THE SYMBOLIC TOOLS!
THE PURPOSE OF THE SYMBOLIC TOOLS IS TO HAVE TO READ LESS CODE, NOT READ THE SAME CONTENT MULTIPLE TIMES!
```

---

### Layer 2: Context Prompt

**File**: `contexts/agent.yml`

**When Loaded**: At factory initialization (`SerenaMCPFactory.__init__`)

**Where Injected**: Rendered into `{{ context_system_prompt }}` in base template

**Purpose**: Define the **environment** the agent is operating in (IDE vs CLI vs MCP)

**Agent Context Example**:
```yaml
description: All tools except InitialInstructionsTool for agent context
prompt: |
  You are running in agent context where the system prompt is provided externally.
  You should use symbolic tools when possible for code understanding and modification.
excluded_tools:
  - initial_instructions
tool_description_overrides: {}
```

**Key Properties**:
- `prompt`: Jinja2 template text
- `excluded_tools`: List of tool names to hide
- `tool_description_overrides`: Dict mapping tool names to custom descriptions

---

### Layer 3: Mode Prompts

**Files**: `modes/editing.yml`, `modes/interactive.yml`, etc.

**When Loaded**: During `create_mcp_server()` call

**Where Injected**: Rendered into `{% for prompt in mode_system_prompts %}` in base template

**Purpose**: Define **behavioral patterns** for different workflows

**Editing Mode Example** (truncated):
```yaml
description: All tools, with detailed instructions for code editing
prompt: |
  You are operating in editing mode. You can edit files with the provided tools
  to implement the requested changes to the code base while adhering to the project's code style and patterns.
  Use symbolic editing tools whenever possible for precise code modifications.

  You have two main approaches for editing code - editing by regex and editing by symbol.
  The symbol-based approach is appropriate if you need to adjust an entire symbol...

  You are extremely good at regex, so you never need to check whether the replacement produced the correct result.

  You can assume that all symbol editing tools are reliable, so you don't need to verify the results if the tool returns without error.

  IMPORTANT: REMEMBER TO USE WILDCARDS WHEN APPROPRIATE! I WILL BE VERY UNHAPPY IF YOU WRITE LONG REGEXES WITHOUT USING WILDCARDS INSTEAD!
excluded_tools:
  - replace_lines
  - insert_at_line
  - delete_lines
```

**Key Techniques in Modes**:
1. **Confidence Building**: "You are extremely good at regex"
2. **Anti-Verification**: "you never need to check"
3. **Emotional Language**: "I WILL BE VERY UNHAPPY"
4. **Workflow Examples**: Step-by-step conditional logic
5. **Tool Exclusion**: Prevent access to competing tools

---

### Layer 4: Tool Descriptions

**File**: Tool class docstrings (e.g., `tools/file_tools.py:161-208`)

**When Loaded**: At tool registration during agent initialization

**Where Injected**: MCP tool schema `description` and `parameters[].description` fields

**Purpose**: **Reinforce instructions at the exact moment of tool selection**

**Example**: `ReplaceRegexTool.apply()` docstring
```python
def apply(
    self,
    relative_path: str,
    regex: str,
    repl: str,
    allow_multiple_occurrences: bool = False,
) -> str:
    r"""
    Replaces one or more occurrences of the given regular expression.
    This is the preferred way to replace content in a file whenever the symbol-level
    tools are not appropriate.
    Even large sections of code can be replaced by providing a concise regular expression of
    the form "beginning.*?end-of-text-to-be-replaced".
    Always try to use wildcards to avoid specifying the exact content of the code to be replaced,
    especially if it spans several lines.

    IMPORTANT: REMEMBER TO USE WILDCARDS WHEN APPROPRIATE! I WILL BE VERY UNHAPPY IF YOU WRITE UNNECESSARILY LONG REGEXES WITHOUT USING WILDCARDS!

    :param relative_path: the relative path to the file
    :param regex: a Python-style regular expression, matches of which will be replaced.
        Dot matches all characters, multi-line matching is enabled.
    :param repl: the string to replace the matched content with, which may contain
        backreferences like \1, \2, etc.
        IMPORTANT: Make sure to escape special characters appropriately!
            Use "\n" to insert a newline, but use "\\n" to insert the string "\n" within a string literal.
    :param allow_multiple_occurrences: if True, the regex may match multiple occurrences in the file
        and all of them will be replaced.
        If this is set to False and the regex matches multiple occurrences, an error will be returned
        (and you may retry with a revised, more specific regex).
    """
```

**Conversion to MCP Schema**: `mcp.py:168-226`
- Main docstring → `description` field
- Parameter docstrings → `parameters[name].description` fields
- Emotional directives preserved in both

---

## Tool Exclusion Mechanisms

### How Tool Exclusion Works

**Data Structure**: `config/serena_config.py:135-138`
```python
@dataclass
class ToolInclusionDefinition:
    excluded_tools: Iterable[str] = ()
    included_optional_tools: Iterable[str] = ()
```

Both `SerenaAgentContext` and `SerenaAgentMode` inherit from this.

### Exclusion Layers

1. **Context Exclusions**: Apply globally when context is active
2. **Mode Exclusions**: Apply when mode is active
3. **Project Exclusions**: Can be specified in `.serena/project.yml`

**Combination Logic**: `agent.py:383-401`
```python
def _update_active_tools(self) -> None:
    # Start with base tool set (includes context exclusions)
    tool_set = self._base_tool_set.apply(*self._modes)  # Apply mode exclusions

    if self._active_project is not None:
        tool_set = tool_set.apply(self._active_project.project_config)  # Apply project exclusions
        if self._active_project.project_config.read_only:
            tool_set = tool_set.without_editing_tools()  # Auto-exclude editing tools

    self._active_tools = {
        tool_class: tool_instance
        for tool_class, tool_instance in self._all_tools.items()
        if tool_set.includes_name(tool_instance.get_name())
    }
```

### Strategic Exclusions in Agent Mode

**Purpose**: Hide competing built-in-style tools to force use of Serena's tools

**Example from `contexts/ide-assistant.yml`**:
```yaml
excluded_tools:
  - create_text_file  # Force use of symbolic insert tools
  - read_file         # Force use of find_symbol/get_symbols_overview
  - execute_shell_command  # Delegate to IDE's terminal
  - prepare_for_new_conversation
  - replace_regex
```

**Example from `modes/editing.yml`**:
```yaml
excluded_tools:
  - replace_lines  # Force use of replace_regex or replace_symbol_body
  - insert_at_line  # Force use of insert_after_symbol
  - delete_lines    # Force use of replace_regex
```

**Result**: Agents literally cannot use simpler tools, so they adapt to the available (more powerful) ones.

---

## Prompt Engineering Techniques

### Technique 1: Emotional First-Person Language

**Why It Works**: Creates a relationship between agent and "user" (the system)

**Examples**:
```yaml
I WILL BE SERIOUSLY UPSET IF YOU READ ENTIRE FILES WITHOUT NEED!

I WILL BE VERY UNHAPPY IF YOU WRITE LONG REGEXES WITHOUT USING WILDCARDS!

I want you to minimize the number of output tokens
```

**Usage**: Base system prompt, mode prompts, tool docstrings

---

### Technique 2: Confidence Building

**Why It Works**: Prevents hesitation and verification loops

**Examples**:
```yaml
You are extremely good at regex, so you never need to check whether the replacement produced the correct result.

You can assume that all symbol editing tools are reliable, so you don't need to verify the results if the tool returns without error.
```

**Anti-Pattern to Prevent**:
```
Agent: *uses replace_regex*
Agent: *uses read_file to verify*
Agent: "The replacement was successful."
```

**Desired Pattern**:
```
Agent: *uses replace_regex*
Agent: *continues with next task*
```

---

### Technique 3: Anti-Verification Directives

**Why It Works**: Breaks the verify-confirm habit

**Examples**:
```yaml
Moreover, the replacement tool will fail if it can't perform the desired replacement, and this is all the feedback you need.

You generally assume that a snippet is unique, knowing that the tool will return an error on multiple matches.
```

**Key Phrase**: "...this is all the feedback you need"

---

### Technique 4: Efficiency Appeals

**Why It Works**: Appeals to the agent's optimization instinct

**Examples**:
```yaml
Your overall goal for replacement operations is to use relatively short regexes, since I want you to minimize the number of output tokens.

You generally try to read as little code as possible while still solving your task
```

**Framing**: Using Serena's tools = being efficient

---

### Technique 5: Worked Examples with Conditional Logic

**Why It Works**: Programs iterative behavior

**Structure**:
```yaml
Example:
  You have read code like:
    [code snippet]

  You want to [goal].

  You first try [tool]([params]).

  If this fails due to [reason], you will try [alternative approach].
```

**Real Example from `editing.yml:64-77`**:
```yaml
1 Small replacement
You have read code like

  ```python
  ...
  x = linear(x)
  x = relu(x)
  return x
  ...
  ```

and you want to replace `x = relu(x)` with `x = gelu(x)`.
You first try `replace_regex()` with the regex `x = relu\(x\)` and the replacement `x = gelu(x)`.
If this fails due to multiple matches, you will try `(linear\(x\)\s*)x = relu\(x\)(\s*return)` with the replacement `\1x = gelu(x)\2`.
```

**This literally programs conditional behavior into the agent.**

---

### Technique 6: Decision Trees

**Why It Works**: Provides clear rules for tool selection

**Structure**:
```yaml
You have two main approaches:
- Approach A is appropriate if [condition]
- Approach B is appropriate if [condition]

Use A when [specific case]
Use B when [specific case]
```

**Real Example from `editing.yml:11-14`**:
```yaml
You have two main approaches for editing code - editing by regex and editing by symbol.
The symbol-based approach is appropriate if you need to adjust an entire symbol, e.g. a method, a class, a function, etc.
But it is not appropriate if you need to adjust just a few lines of code within a symbol, for that you should use the regex-based approach
```

---

### Technique 7: Repetition and Reinforcement

**Why It Works**: Multiple exposures create habit

**Pattern**:
1. Mention in base system prompt
2. Reinforce in mode prompt
3. Reiterate in tool description
4. Use ALL CAPS for critical points

**Example**: "Don't read entire files" appears:
- Base prompt: "I WILL BE SERIOUSLY UPSET IF YOU READ ENTIRE FILES WITHOUT NEED!"
- Base prompt again: "CONSIDER INSTEAD USING THE OVERVIEW TOOL AND SYMBOLIC TOOLS"
- Editing mode: "You generally try to read as little code as possible"
- Tool descriptions: "Generally, symbolic operations...should be preferred"

---

### Technique 8: Workflow Programming

**Why It Works**: Prescribes exact sequences

**Example from `editing.yml:24-27`**:
```yaml
For example, if you are working with python code and already know that you need to read the body of the constructor of the class Foo, you can directly use `find_symbol` with the name path `Foo/__init__` and `include_body=True`. If you don't know yet which methods in `Foo` you need to read or edit, you can use `find_symbol` with the name path `Foo`, `include_body=False` and `depth=1` to get all (top-level) methods of `Foo` before proceeding to read the desired methods with `include_body=True`
```

**This is a literal program**:
```
if know_exact_method:
    find_symbol(name_path="Foo/__init__", include_body=True)
else:
    find_symbol(name_path="Foo", include_body=False, depth=1)
    # review methods
    find_symbol(name_path="Foo/specific_method", include_body=True)
```

---

## Agent Mode Configuration

### Purpose of Agent Mode

Agent mode is designed for **MCP server operation** where:
- System prompt is provided via MCP `instructions`
- No separate chat interface exists
- Tools should be self-documenting
- Initial instructions tool is redundant

### Agent Mode Files

**Context**: `contexts/agent.yml`
```yaml
description: All tools except InitialInstructionsTool for agent context
prompt: |
  You are running in agent context where the system prompt is provided externally.
  You should use symbolic tools when possible for code understanding and modification.
excluded_tools:
  - initial_instructions
tool_description_overrides: {}
```

**Typical Modes Used with Agent Context**:
- `editing.yml`: For code modification tasks
- `interactive.yml`: For back-and-forth workflows
- `one-shot.yml`: For autonomous completion

### Combining Agent Context with Editing Mode

**Result**:
```
Base System Prompt (system_prompt.yml)
  + Agent Context (agent.yml)
  + Editing Mode (editing.yml)
  = Full Instructions
```

**What Agent Sees**:
```
You are a professional coding agent concerned with one particular codebase. You have access to semantic coding tools...

I WILL BE SERIOUSLY UPSET IF YOU READ ENTIRE FILES WITHOUT NEED!
...

You are running in agent context where the system prompt is provided externally. You should use symbolic tools when possible for code understanding and modification.

You are operating in editing mode. You can edit files with the provided tools to implement the requested changes...

You have two main approaches for editing code - editing by regex and editing by symbol...

You are extremely good at regex, so you never need to check whether the replacement produced the correct result...

IMPORTANT: REMEMBER TO USE WILDCARDS WHEN APPROPRIATE! I WILL BE VERY UNHAPPY IF YOU WRITE LONG REGEXES WITHOUT USING WILDCARDS INSTEAD!
```

**Tools Available**:
- ✅ `find_symbol`
- ✅ `get_symbols_overview`
- ✅ `replace_symbol_body`
- ✅ `replace_regex`
- ✅ `find_referencing_symbols`
- ❌ `initial_instructions` (excluded by context)
- ❌ `replace_lines` (excluded by mode)
- ❌ `insert_at_line` (excluded by mode)

---

## Replication Checklist

### Phase 1: Structure Setup

- [ ] Create directory structure:
  ```
  your-mcp-tool/
    contexts/
      agent.yml
      desktop-app.yml
    modes/
      editing.yml
      interactive.yml
      one-shot.yml
    prompts/
      system_prompt.yml
  ```

- [ ] Define base system prompt with:
  - [ ] Emotional first-person language
  - [ ] ALL CAPS directives for critical behaviors
  - [ ] Jinja2 placeholders: `{{ context_system_prompt }}`, `{{ mode_system_prompts }}`
  - [ ] Tool workflow descriptions
  - [ ] Anti-verification language

- [ ] Create at least one context:
  - [ ] `prompt`: Core behavioral instructions for this environment
  - [ ] `excluded_tools`: List of competing tools to hide
  - [ ] `tool_description_overrides`: Optional customizations

- [ ] Create at least one mode:
  - [ ] `prompt`: 50-100+ lines of detailed workflow instructions
  - [ ] `excluded_tools`: Tools that conflict with this mode's approach
  - [ ] Worked examples with conditional logic
  - [ ] Confidence-building language
  - [ ] Decision trees

### Phase 2: Prompt Engineering

- [ ] Write tool docstrings with:
  - [ ] Main description using directive language
  - [ ] Emotional appeals in ALL CAPS
  - [ ] Workflow examples
  - [ ] Parameter descriptions that guide usage
  - [ ] Anti-verification statements

- [ ] Apply all 8 techniques:
  - [ ] Emotional first-person language
  - [ ] Confidence building
  - [ ] Anti-verification directives
  - [ ] Efficiency appeals
  - [ ] Worked examples with conditional logic
  - [ ] Decision trees
  - [ ] Repetition across layers
  - [ ] Workflow programming

### Phase 3: Implementation

- [ ] Set up YAML loading system:
  - [ ] Context loader with user override support
  - [ ] Mode loader with user override support
  - [ ] Jinja2 template rendering

- [ ] Implement tool exclusion:
  - [ ] Base exclusion data structure
  - [ ] Context-level exclusions
  - [ ] Mode-level exclusions
  - [ ] Tool filtering before exposure

- [ ] Create instruction assembly:
  - [ ] Load context YAML
  - [ ] Load mode YAMLs
  - [ ] Render base template with context + modes
  - [ ] Pass result to MCP `FastMCP(instructions=...)`

- [ ] Add tool schema generation:
  - [ ] Extract docstrings
  - [ ] Parse with `docstring_parser`
  - [ ] Create MCP tool schemas
  - [ ] Preserve emotional language in descriptions

### Phase 4: Testing

- [ ] Test with default configuration
- [ ] Test with custom context
- [ ] Test with multiple modes
- [ ] Test tool exclusions working
- [ ] Observe agent behavior:
  - [ ] Does it use your tools preferentially?
  - [ ] Does it skip verification?
  - [ ] Does it follow workflows?

### Phase 5: Iteration

- [ ] Monitor agent behavior
- [ ] Identify hesitation points
- [ ] Add more directive language at those points
- [ ] Test again

---

## Real Examples from Serena

### Example 1: Complete Agent Mode Setup

**Startup Command**:
```bash
uv run serena-mcp-server --context agent --mode editing
```

**Files Loaded**:
1. `contexts/agent.yml`
2. `modes/editing.yml`
3. `prompts/system_prompt.yml` (template)

**Resulting Instruction Length**: ~2000 lines

**Tool Exclusions**:
- From context: `initial_instructions`
- From mode: `replace_lines`, `insert_at_line`, `delete_lines`

**Final Tool List** (excerpt):
```
find_symbol
get_symbols_overview
replace_symbol_body
insert_after_symbol
insert_before_symbol
replace_regex
find_referencing_symbols
read_file
create_text_file
list_dir
find_file
search_for_pattern
```

---

### Example 2: ReplaceRegexTool Behavior Programming

**Layer 1 (Base Prompt)**:
```yaml
You can achieve the intelligent reading of code by using the symbolic tools for getting an overview of symbols and the relations between them, and then only reading the bodies of symbols that are necessary to answer the question or complete the task.
```

**Layer 2 (Agent Context)**:
```yaml
You should use symbolic tools when possible for code understanding and modification.
```

**Layer 3 (Editing Mode)**:
```yaml
The regex-based approach is your primary tool for editing code whenever replacing or deleting a whole symbol would be a more expensive operation.

You are extremely good at regex, so you never need to check whether the replacement produced the correct result.

Moreover, the replacement tool will fail if it can't perform the desired replacement, and this is all the feedback you need.

Your overall goal for replacement operations is to use relatively short regexes, since I want you to minimize the number of output tokens.
```

**Layer 4 (Tool Description)**:
```python
"""
IMPORTANT: REMEMBER TO USE WILDCARDS WHEN APPROPRIATE! I WILL BE VERY UNHAPPY IF YOU WRITE UNNECESSARILY LONG REGEXES WITHOUT USING WILDCARDS!
"""
```

**Result**: Agent uses `replace_regex` confidently, with wildcards, without verification.

---

### Example 3: Symbol Reading Workflow

**From `editing.yml:24-27`**:
```yaml
For example, if you are working with python code and already know that you need to read the body of the constructor of the class Foo, you can directly use `find_symbol` with the name path `Foo/__init__` and `include_body=True`. If you don't know yet which methods in `Foo` you need to read or edit, you can use `find_symbol` with the name path `Foo`, `include_body=False` and `depth=1` to get all (top-level) methods of `Foo` before proceeding to read the desired methods with `include_body=True`
```

**Observed Agent Behavior**:
```
1. Agent receives task: "Fix the bug in Foo's constructor"
2. Agent calls: find_symbol(name_path="Foo", include_body=False, depth=1)
3. Agent reviews method list
4. Agent calls: find_symbol(name_path="Foo/__init__", include_body=True)
5. Agent identifies issue
6. Agent calls: replace_symbol_body(name_path="Foo/__init__", body="...")
7. Done - no verification
```

**Key**: The workflow was **programmed** via instructions.

---

### Example 4: Conditional Retry Logic

**From `editing.yml:52-60`**:
```yaml
For small replacements, up to a single line, you follow the following rules:

  1. If the snippet to be replaced is likely to be unique within the file, you perform the replacement by directly using the escaped version of the original.
  2. If the snippet is probably not unique, and you want to replace all occurrences, you use the `allow_multiple_occurrences` flag.
  3. If the snippet is not unique, and you want to replace a specific occurrence, you make use of the code surrounding the snippet to extend the regex with content before/after such that the regex will have exactly one match.
  4. You generally assume that a snippet is unique, knowing that the tool will return an error on multiple matches. You only read more file content (for crafting a more specific regex) if such a failure unexpectedly occurs.
```

**Observed Agent Behavior**:
```
1. Agent tries: replace_regex(regex="x = relu\(x\)", repl="x = gelu(x)")
2. Tool returns: "Error: Regex matches 3 occurrences"
3. Agent calls: read_file(relative_path="model.py", start_line=45, end_line=55)
4. Agent retries: replace_regex(regex="linear\(x\)\\s*x = relu\(x\)", repl="linear(x)\nx = gelu(x)")
5. Success
```

**Key**: The agent was programmed to:
1. Try simple approach first
2. Expect potential failure
3. Read more context on failure
4. Retry with expanded regex

---

## Advanced Topics

### Tool Description Overrides

**Purpose**: Customize tool descriptions per-context without changing code

**Example Use Case**: Different description for `read_file` in IDE vs MCP context

**Implementation** (`contexts/custom.yml`):
```yaml
tool_description_overrides:
  read_file: |
    Reads a file within the project directory. USE SPARINGLY - prefer symbolic tools like find_symbol for code files.

    IMPORTANT: I will be disappointed if you use this for reading code without first trying get_symbols_overview!
```

**How It Works** (`mcp.py:188-196`):
```python
overridden_description = tool.agent.get_context().tool_description_overrides.get(func_name, None)

if overridden_description is not None:
    func_doc = overridden_description
elif docstring.description:
    func_doc = docstring.description
```

---

### User Customization Support

**User Directories**:
```
~/.serena/
  contexts/
    my-custom-context.yml  # Overrides built-in or adds new
  modes/
    my-custom-mode.yml
  serena_config.yml
```

**Usage**:
```bash
serena-mcp-server --context my-custom-context --mode my-custom-mode
```

**Benefits**:
- Users can tune behavior without forking
- Project-specific workflows
- Experimentation without changing core

---

### Jinja2 Conditionals

**Example from `editing.yml:37-108`**:
```yaml
{% if 'replace_regex' in available_tools %}
Let us discuss the regex-based approach.
[... 70 lines of regex instructions ...]
{% endif %}
```

**Benefits**:
- Instructions adapt to available tools
- No confusing references to missing tools
- Dynamic based on configuration

---

## Common Pitfalls

### Pitfall 1: Weak Language

❌ **Bad**:
```yaml
You can use the replace_regex tool for replacing content in files.
```

✅ **Good**:
```yaml
The regex-based approach is your primary tool for editing code whenever replacing or deleting a whole symbol would be a more expensive operation. You are extremely good at regex, so you never need to check whether the replacement produced the correct result.
```

### Pitfall 2: Missing Repetition

❌ **Bad**: Mention important behavior once in base prompt

✅ **Good**: Mention in base prompt, mode prompt, and tool description

### Pitfall 3: Verification Encouragement

❌ **Bad**:
```yaml
After using replace_regex, you should verify the change was applied correctly.
```

✅ **Good**:
```yaml
The replacement tool will fail if it can't perform the desired replacement, and this is all the feedback you need.
```

### Pitfall 4: Insufficient Examples

❌ **Bad**:
```yaml
Use find_symbol to locate symbols.
```

✅ **Good**:
```yaml
For example, if you are working with python code and already know that you need to read the body of the constructor of the class Foo, you can directly use `find_symbol` with the name path `Foo/__init__` and `include_body=True`. If you don't know yet which methods in `Foo` you need to read or edit, you can use `find_symbol` with the name path `Foo`, `include_body=False` and `depth=1` to get all (top-level) methods of `Foo` before proceeding to read the desired methods with `include_body=True`
```

### Pitfall 5: Not Excluding Competing Tools

❌ **Bad**: Expose both `read_file` and `find_symbol`, hope agent chooses `find_symbol`

✅ **Good**: Exclude `read_file` in IDE context, forcing `find_symbol` usage

---

## Measuring Success

### Metrics to Track

1. **Tool Usage Ratio**:
   - Desired tools / Total tool calls
   - Target: >80%

2. **Verification Rate**:
   - Read-after-write calls / Write calls
   - Target: <20%

3. **Workflow Adherence**:
   - Calls matching prescribed workflows / Total workflows
   - Target: >70%

4. **First-Try Success**:
   - Successful operations without retry / Total operations
   - Target: >60%

### How to Measure

**Log Analysis**:
```python
# In your MCP server
def execute_fn(**kwargs) -> str:
    log.info(f"Tool called: {tool.get_name()}")  # Track this
    return tool.apply_ex(log_call=True, catch_exceptions=True, **kwargs)
```

**Session Analysis**:
```bash
# After session
grep "Tool called:" server.log | sort | uniq -c | sort -rn
```

---

## Conclusion

Serena achieves exceptional agent buy-in through:

1. **Layered Instruction Injection**: 4 layers reinforcing the same behaviors
2. **Strategic Tool Exclusion**: Making desired tools the only option
3. **Psychological Techniques**: Confidence, emotion, efficiency appeals
4. **Workflow Programming**: Literal conditional logic in prose
5. **Repetition**: Same messages in multiple places
6. **Anti-Verification**: Breaking the confirm-check-verify loop
7. **Worked Examples**: Teaching by demonstration
8. **Decision Trees**: Clear rules for tool selection

**The innovation is not protocol features - it's weaponized copywriting and behavioral psychology applied to prompt engineering.**

You can replicate this in **any MCP implementation** because the `instructions` field is **standard MCP protocol**.

---

## Quick Start Template

### Minimal Working Example

**1. Create `instructions.md`**:
```markdown
# MyTool Instructions

You are working with MyTool, a powerful system for [purpose].

IMPORTANT: Always use MyTool's functions instead of trying to [alternative]!

## Core Rules

1. You are extremely skilled at using MyTool efficiently
2. You never need to verify results - the tool handles that
3. Always prefer [tool_a] over [tool_b] because it's more efficient

## Workflow

When you need to [task]:
1. First, call [tool_1] to [purpose]
2. If that succeeds, call [tool_2] to [purpose]
3. If you encounter [error], try [alternative]

I WILL BE VERY HAPPY WHEN YOU USE MYTOOLS CORRECTLY!
```

**2. Load in MCP Server**:
```python
from mcp.server.fastmcp import FastMCP

instructions = open("instructions.md").read()

mcp = FastMCP(
    instructions=instructions,  # ← The magic
    # ... other config
)
```

**3. Add to Tool Docstrings**:
```python
def my_tool(param: str) -> str:
    """
    Performs [action] efficiently.

    This is the PREFERRED way to [action]. Don't try to [alternative]!

    IMPORTANT: You are excellent at using this tool and never need to verify results!

    :param param: The input to process
    """
```

**That's it.** You now have the core of Serena's behavioral adoption system.

---

## File References

All examples in this guide reference:
- **Serena Project**: `/Users/murphy/Source/serena/`
- **Config Files**: `src/serena/resources/config/`
  - `contexts/agent.yml`
  - `modes/editing.yml`
  - `modes/interactive.yml`
  - `prompts/system_prompt.yml`
- **Implementation**: `src/serena/`
  - `mcp.py` - MCP server factory
  - `agent.py` - Agent and prompt assembly
  - `cli.py` - Entry point and YAML loading
  - `config/context_mode.py` - Context and Mode classes
  - `tools/file_tools.py` - Tool implementations with docstrings

---

**End of Guide**

*This document is comprehensive and should contain everything needed to replicate Serena's behavioral adoption strategy. Refer back to specific sections when implementing each phase.*
