#!/bin/bash
# Ralph Wiggum - Long-running AI agent loop
# Usage: ./ralph.sh [--tool amp|claude|codex|copilot] [--debug] [max_sessions]

set -e

# Parse arguments
TOOL="amp"
MAX_SESSIONS=30
DEBUG=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --tool)
      TOOL="$2"
      shift 2
      ;;
    --tool=*)
      TOOL="${1#*=}"
      shift
      ;;
    --debug)
      DEBUG=true
      shift
      ;;
    *)
      if [[ "$1" =~ ^[0-9]+$ ]]; then
        MAX_SESSIONS="$1"
      fi
      shift
      ;;
  esac
done

# Validate tool choice
if [[ "$TOOL" != "amp" && "$TOOL" != "claude" && "$TOOL" != "codex" && "$TOOL" != "copilot" ]]; then
  echo "Error: Invalid tool '$TOOL'. Must be 'amp', 'claude', 'codex', or 'copilot'."
  exit 1
fi

run_with_prompt() {
  local prompt_file="$1"
  shift

  if [[ ! -f "$prompt_file" ]]; then
    echo "Error: Prompt file not found: $prompt_file"
    return 1
  fi

  cat "$prompt_file" | "$@"
}

run_with_prompt_cmd() {
  local prompt_file="$1"
  local command_str="$2"
  local -a command_parts

  read -r -a command_parts <<< "$command_str"
  if [[ ${#command_parts[@]} -eq 0 ]]; then
    echo "Error: Empty command override for $TOOL"
    return 1
  fi

  if ! command -v "${command_parts[0]}" >/dev/null 2>&1; then
    echo "Error: Command '${command_parts[0]}' not found in PATH."
    return 1
  fi

  run_with_prompt "$prompt_file" "${command_parts[@]}"
}

current_story_id() {
  if [ ! -f "$STATE_FILE" ]; then
    echo ""
    return 0
  fi

  jq -r '.currentStory // empty' "$STATE_FILE" 2>/dev/null || echo ""
}

completed_story_count() {
  jq '[.userStories[] | select(.passes == true)] | length' "$PRD_FILE" 2>/dev/null || echo "0"
}

story_validation_command() {
  local story_id="$1"

  if [ -z "$story_id" ]; then
    echo ""
    return 0
  fi

  jq -r --arg id "$story_id" '
    ([.userStories[] | select(.id == $id)] | first) as $story
    | (
        $story.validationCommand
        // (
          ($story.acceptanceCriteria // [])
          | map(
              select(test("^Run `.+` and it passes\\.?$"))
              | capture("^Run `(?<cmd>.+)` and it passes\\.?$").cmd
            )
          | first
        )
        // empty
      )
  ' "$PRD_FILE" 2>/dev/null || echo ""
}

git_head_sha() {
  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo ""
    return 0
  fi

  git rev-parse HEAD 2>/dev/null || echo ""
}

git_worktree_dirty() {
  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    return 1
  fi

  [ -n "$(git status --porcelain 2>/dev/null)" ]
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PRD_FILE="$SCRIPT_DIR/prd.json"
PROGRESS_FILE="$SCRIPT_DIR/progress.md"
ARCHIVE_DIR="$SCRIPT_DIR/archive"
STATE_FILE="$SCRIPT_DIR/state.json"
LAST_BRANCH_FILE="$SCRIPT_DIR/.last-branch"

# Validate required files exist
if [ ! -f "$PRD_FILE" ]; then
  echo "Error: PRD file not found at $PRD_FILE"
  echo "Create a prd.json first (see prd.json.example)."
  exit 1
fi

# Validate PRD is valid JSON
if ! jq empty "$PRD_FILE" 2>/dev/null; then
  echo "Error: $PRD_FILE is not valid JSON."
  exit 1
fi

# Validate required PRD fields
if ! jq -e '.project and .branchName and .userStories and (.userStories | length > 0)' "$PRD_FILE" > /dev/null 2>&1; then
  echo "Error: $PRD_FILE is missing required fields (project, branchName, userStories)."
  exit 1
fi

# Archive previous run if branch marker changed. This marker is local and can be stale
# after copying Ralph files between projects, so never reset tracked progress/state here.
if [ -f "$LAST_BRANCH_FILE" ]; then
  CURRENT_BRANCH=$(jq -r '.branchName // empty' "$PRD_FILE" 2>/dev/null || echo "")
  LAST_BRANCH=$(cat "$LAST_BRANCH_FILE" 2>/dev/null || echo "")

  if [ -n "$CURRENT_BRANCH" ] && [ -n "$LAST_BRANCH" ] && [ "$CURRENT_BRANCH" != "$LAST_BRANCH" ]; then
    DATE=$(date +%Y-%m-%d)
    FOLDER_NAME=$(echo "$LAST_BRANCH" | sed 's|^ralph/||')
    ARCHIVE_FOLDER="$ARCHIVE_DIR/$DATE-$FOLDER_NAME"

    echo "Ralph branch marker changed: $LAST_BRANCH -> $CURRENT_BRANCH"
    echo "Archiving a snapshot but preserving existing progress/state files."
    mkdir -p "$ARCHIVE_FOLDER"
    [ -f "$PRD_FILE" ] && cp "$PRD_FILE" "$ARCHIVE_FOLDER/"
    [ -f "$PROGRESS_FILE" ] && cp "$PROGRESS_FILE" "$ARCHIVE_FOLDER/"
    [ -f "$STATE_FILE" ] && cp "$STATE_FILE" "$ARCHIVE_FOLDER/"
    echo "   Archived to: $ARCHIVE_FOLDER"
    echo "   Existing $PROGRESS_FILE and $STATE_FILE were left unchanged."
  fi
fi

# Track current branch
CURRENT_BRANCH=$(jq -r '.branchName // empty' "$PRD_FILE" 2>/dev/null || echo "")
if [ -n "$CURRENT_BRANCH" ]; then
  echo "$CURRENT_BRANCH" > "$LAST_BRANCH_FILE"
fi

# Initialize progress file if it doesn't exist
if [ ! -f "$PROGRESS_FILE" ]; then
  echo "# Ralph Progress Log" > "$PROGRESS_FILE"
  echo "Started: $(date)" >> "$PROGRESS_FILE"
  echo "---" >> "$PROGRESS_FILE"
  echo "" >> "$PROGRESS_FILE"
  echo "## Codebase Patterns" >> "$PROGRESS_FILE"
  echo "> Reusable patterns discovered during implementation. Read this FIRST every session." >> "$PROGRESS_FILE"
fi

# Bootstrap state.json if it doesn't exist
if [ ! -f "$STATE_FILE" ]; then
  echo "Bootstrapping state.json from prd.json..."
  FIRST_STORY_ID=$(jq -r '[.userStories[] | select(.passes == false)] | sort_by(.priority) | first | .id // empty' "$PRD_FILE")
  FIRST_STORY_TITLE=$(jq -r '[.userStories[] | select(.passes == false)] | sort_by(.priority) | first | .title // empty' "$PRD_FILE")
  PRD_BRANCH=$(jq -r '.branchName // ""' "$PRD_FILE")

  if [ -n "$FIRST_STORY_ID" ]; then
    ITER_MODE=$(jq -r --arg id "$FIRST_STORY_ID" '[.userStories[] | select(.id == $id)] | first | .iterationMode // empty' "$PRD_FILE")
    MAX_ITER=$(jq -r --arg id "$FIRST_STORY_ID" '[.userStories[] | select(.id == $id)] | first | .maxIterations // 0' "$PRD_FILE")

    if [ -n "$ITER_MODE" ] && [ "$ITER_MODE" != "null" ]; then
      NEXT_ACTION="iteration 1/$MAX_ITER"
    else
      NEXT_ACTION="implement"
    fi

    jq -n \
      --arg branch "$PRD_BRANCH" \
      --arg story "$FIRST_STORY_ID" \
      --arg title "$FIRST_STORY_TITLE" \
      --arg action "$NEXT_ACTION" \
      --arg date "$(date +%Y-%m-%d)" \
      '{
        branch: $branch,
        currentStory: $story,
        storyTitle: $title,
        nextAction: $action,
        progressTokens: 0,
        compactionNeeded: false,
        compactionThreshold: 10000,
        lastUpdated: $date
      }' > "$STATE_FILE"
    echo "   Created state.json: $FIRST_STORY_ID - $FIRST_STORY_TITLE"
  fi
fi

echo "Starting Ralph - Tool: $TOOL - Max sessions: $MAX_SESSIONS - Debug: $DEBUG"

for i in $(seq 1 $MAX_SESSIONS); do
  echo ""
  echo "==============================================================="
  echo "  Ralph Session $i of $MAX_SESSIONS ($TOOL)"
  echo "==============================================================="

  SESSION_START_STORY=$(current_story_id)
  SESSION_START_COMPLETED=$(completed_story_count)
  SESSION_START_VALIDATION=$(story_validation_command "$SESSION_START_STORY")
  SESSION_START_HEAD=$(git_head_sha)

  # Run the selected tool with the corresponding Ralph prompt
  if [[ "$TOOL" == "amp" ]]; then
    AMP_CMD="${RALPH_AMP_CMD:-amp --dangerously-allow-all}"
    OUTPUT=$(run_with_prompt_cmd "$SCRIPT_DIR/prompt.md" "$AMP_CMD" 2>&1 | tee /dev/stderr) || true
  elif [[ "$TOOL" == "claude" ]]; then
    if [[ -n "${RALPH_CLAUDE_CMD:-}" ]]; then
      OUTPUT=$(run_with_prompt_cmd "$SCRIPT_DIR/CLAUDE.md" "$RALPH_CLAUDE_CMD" 2>&1 | tee /dev/stderr) || true
    else
      CLAUDE_ARGS=(
        --dangerously-skip-permissions
        --print
      )
      if [[ "$DEBUG" == "true" ]]; then
        CLAUDE_ARGS+=(--output-format stream-json --verbose --include-partial-messages)
      fi

      OUTPUT=$(run_with_prompt "$SCRIPT_DIR/CLAUDE.md" claude "${CLAUDE_ARGS[@]}" 2>&1 | tee /dev/stderr) || true
    fi
  elif [[ "$TOOL" == "codex" ]]; then
    CODEX_CMD="${RALPH_CODEX_CMD:-codex exec --dangerously-bypass-approvals-and-sandbox}"
    OUTPUT=$(run_with_prompt_cmd "$SCRIPT_DIR/CODEX.md" "$CODEX_CMD" 2>&1 | tee /dev/stderr) || true
  else
    COPILOT_CMD="${RALPH_COPILOT_CMD:-gh copilot agent run}"
    OUTPUT=$(run_with_prompt_cmd "$SCRIPT_DIR/COPILOT.md" "$COPILOT_CMD" 2>&1 | tee /dev/stderr) || true
  fi

  SESSION_END_STORY=$(current_story_id)
  SESSION_END_COMPLETED=$(completed_story_count)
  SESSION_END_HEAD=$(git_head_sha)
  STORY_ADVANCED=false

  if [ -n "$SESSION_START_STORY" ] && [ "$SESSION_END_STORY" != "$SESSION_START_STORY" ]; then
    STORY_ADVANCED=true
  elif [ "$SESSION_END_COMPLETED" -gt "$SESSION_START_COMPLETED" ]; then
    STORY_ADVANCED=true
  fi

  if [ "$STORY_ADVANCED" = "true" ]; then
    if [ -n "$SESSION_START_VALIDATION" ]; then
      echo "Running validation for completed story $SESSION_START_STORY: $SESSION_START_VALIDATION"
      if ! bash -lc "$SESSION_START_VALIDATION"; then
        echo "Error: Story $SESSION_START_STORY failed validation command: $SESSION_START_VALIDATION"
        exit 1
      fi
    fi

    if [ -n "$SESSION_START_HEAD" ] || [ -n "$SESSION_END_HEAD" ]; then
      if [ "$SESSION_START_HEAD" = "$SESSION_END_HEAD" ]; then
        echo "Error: Story $SESSION_START_STORY completed without a git commit."
        exit 1
      fi

      if git_worktree_dirty; then
        echo "Error: Story $SESSION_START_STORY advanced with uncommitted changes in the worktree."
        exit 1
      fi
    fi
  fi

  # Check for completion by reading prd.json directly (ground truth)
  # Immune to false positives from agent text output
  ALL_PASS=$(jq '[.userStories[].passes] | all' "$PRD_FILE" 2>/dev/null || echo "false")
  if [ "$ALL_PASS" = "true" ]; then
    echo ""
    echo "Ralph completed all tasks!"
    echo "Completed at session $i of $MAX_SESSIONS"
    exit 0
  fi

  # Validate state.json integrity after session
  if [ -f "$STATE_FILE" ]; then
    if ! jq -e '.currentStory and .lastUpdated and .branch' "$STATE_FILE" > /dev/null 2>&1; then
      echo "Warning: state.json may be malformed after session $i. Check manually."
    fi
  fi

  echo "Session $i complete. Continuing..."
  sleep 2
done

echo ""
echo "Ralph reached max sessions ($MAX_SESSIONS) without completing all tasks."
echo "Check $PROGRESS_FILE for status."
exit 1
