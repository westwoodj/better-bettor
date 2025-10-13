from typing import Optional, Any, Dict
import logging
import os
import json

logger = logging.getLogger(__name__)


class GoogleGenAIClient:
    """Thin wrapper around the `google-genai` library.

    This wrapper attempts to import the library lazily. If the library is not
    installed or credentials are not configured, the wrapper will fall back to
    a safe mock response so the rest of the flow can be exercised without
    contacting the real API during development.
    """

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or os.environ.get("GOOGLE_GENAI_API_KEY")
        self.model = model or os.environ.get("GOOGLE_GENAI_MODEL", "models/text-bison-001")
        self._client = None

    def _ensure_client(self) -> bool:
        if self._client is not None:
            return True
        try:
            import google_genai as gg

            # Keep module reference for later use
            self._client = gg
            return True
        except Exception as exc:  # ImportError or any other issue
            logger.debug("google_genai import failed: %s", exc)
            self._client = None
            return False

    def generate_text(self, prompt: str, temperature: float = 0.0, max_output_tokens: int = 512) -> Dict[str, Any]:
        """Generate text from the model.

        Returns a dict containing at least 'raw_text'. If the real client is
        available we'll attempt to call it; otherwise we return a mocked reply.
        """
        if self._ensure_client():
            try:
                gg = self._client
                # Common patterns: gg.Client(), gg.generate_text(...)
                if hasattr(gg, "Client"):
                    client = gg.Client()
                    if hasattr(client, "generate_text"):
                        resp = client.generate_text(model=self.model, prompt=prompt, temperature=temperature, max_output_tokens=max_output_tokens)
                        return {"raw_text": str(resp)}
                # fallback to module-level generate_text
                if hasattr(gg, "generate_text"):
                    resp = gg.generate_text(model=self.model, prompt=prompt, temperature=temperature, max_output_tokens=max_output_tokens)
                    return {"raw_text": str(resp)}
            except Exception as exc:
                logger.exception("Error calling google-genai client: %s", exc)
                # fall through to mocked response

        # Mocked/default response when real client is unavailable or failed.
        mock_text = (
            "Recommendation:\n"
            "- Spread: Home -3.5\n"
            "- Moneyline: Home -180\n"
            "- Total: 44.5 (Over)\n"
            "- Player Props: Player X over 22.5 rushing yards\n"
            "Rationale: Home team has stronger rush defense and home-field advantage."
        )
        return {"raw_text": mock_text}

    def _parse_function_call_from_payload(self, payload: Any) -> Optional[Dict[str, Any]]:
        """Attempt to locate a function/tool call in various response payload shapes.

        Returns {'name': ..., 'arguments': {...}} or None.
        """
        # Helper to normalize argument string -> dict
        def _parse_args(a):
            if a is None:
                return {}
            if isinstance(a, dict):
                return a
            if isinstance(a, str):
                try:
                    return json.loads(a)
                except Exception:
                    # some clients may provide a simple key=value string; best-effort skip
                    return {}
            return {}

        try:
            # 1) Google Responses API: object with .output or .candidates
            # Try common attributes defensively
            # payload may be a protobuf-like object; cast to dict-ish by inspecting attributes
            # Check for 'output' attribute (list of messages)
            out = getattr(payload, "output", None)
            if out:
                # each item may be a dict-like or an object with 'content'
                for item in out:
                    content = None
                    if isinstance(item, dict):
                        content = item.get("content")
                    else:
                        content = getattr(item, "content", None)
                    if not content:
                        continue
                    for c in content:
                        # c may be dict with type 'tool_call' or 'tool_call' key
                        if isinstance(c, dict):
                            tctype = c.get("type")
                            if tctype and tctype in ("tool_call", "function_call"):
                                tc = c.get("tool_call") or c.get("function_call") or c.get("toolCall")
                                if isinstance(tc, dict):
                                    name = tc.get("name")
                                    args = tc.get("arguments") or tc.get("args")
                                    return {"name": name, "arguments": _parse_args(args)}
                        else:
                            # object-like c
                            tc = getattr(c, "tool_call", None) or getattr(c, "function_call", None) or getattr(c, "toolCall", None)
                            if tc:
                                name = getattr(tc, "name", None)
                                args = getattr(tc, "arguments", None) or getattr(tc, "args", None)
                                return {"name": name, "arguments": _parse_args(args)}

            # 2) Candidates: resp.candidates or resp.candidates[0].content
            cand = getattr(payload, "candidates", None)
            if cand:
                for candidate in cand:
                    # candidate may have content list
                    content = getattr(candidate, "content", None) or getattr(candidate, "message", None) or (candidate if isinstance(candidate, dict) else None)
                    if isinstance(content, dict) and content.get("function_call"):
                        fc = content.get("function_call")
                        name = fc.get("name")
                        args = fc.get("arguments")
                        return {"name": name, "arguments": _parse_args(args)}
                    # try object content
                    if hasattr(candidate, "message"):
                        msg = getattr(candidate, "message")
                        fc = None
                        if isinstance(msg, dict):
                            fc = msg.get("function_call")
                        else:
                            fc = getattr(msg, "function_call", None)
                        if fc:
                            name = fc.get("name") if isinstance(fc, dict) else getattr(fc, "name", None)
                            args = fc.get("arguments") if isinstance(fc, dict) else getattr(fc, "arguments", None)
                            return {"name": name, "arguments": _parse_args(args)}

            # 3) OpenAI-like structure: dict with 'choices' -> message -> function_call
            if isinstance(payload, dict):
                if "choices" in payload and payload["choices"]:
                    choice = payload["choices"][0]
                    msg = choice.get("message") or choice.get("text")
                    if isinstance(msg, dict):
                        fc = msg.get("function_call")
                        if fc:
                            name = fc.get("name")
                            args = fc.get("arguments")
                            return {"name": name, "arguments": _parse_args(args)}
                # direct function_call in top-level
                if "function_call" in payload:
                    fc = payload.get("function_call")
                    name = fc.get("name")
                    args = fc.get("arguments")
                    return {"name": name, "arguments": _parse_args(args)}

            # 4) If payload is a simple string that encodes a JSON instructing a function call, attempt to find a pattern
            if isinstance(payload, str):
                # e.g., function call encoded like: CALL get_depth_chart {"team_name":"Bills","year":2025}
                import re

                m = re.search(r"(get_depth_chart|getDepthChart)\s*(\{.*\})", payload)
                if m:
                    name = m.group(1)
                    try:
                        args = json.loads(m.group(2))
                    except Exception:
                        args = {}
                    return {"name": name, "arguments": args}
        except Exception as exc:
            logger.exception("Error parsing function call from payload: %s", exc)
        return None

    def call_with_functions(self, prompt: str, functions: Optional[list] = None, temperature: float = 0.0, max_output_tokens: int = 1024) -> Dict[str, Any]:
        """Call the model and allow it to return a function call instruction.

        Returns a dict with keys:
        - 'raw_text': textual reply if any
        - 'function_call': { 'name': str, 'arguments': dict } if model requested a function call

        This method attempts to call a real google-genai Responses client (if
        installed) and extract a function call. If that fails or no function
        call is produced, it falls back to a developer-friendly mock that
        recognizes depth-chart prompts for local testing.
        """
        # Try real client first
        if self._ensure_client():
            try:
                gg = self._client
                # Prefer ResponsesClient when available
                if hasattr(gg, "ResponsesClient"):
                    client = gg.ResponsesClient()
                    # The client may accept either keyword args or a request object
                    request = {"model": self.model, "input": prompt, "temperature": temperature}
                    if functions is not None:
                        request["functions"] = functions
                    # defensive call patterns
                    resp = None
                    if hasattr(client, "generate"):
                        try:
                            # Some versions expect a single dict/kwargs; try both
                            resp = client.generate(**request)
                        except TypeError:
                            try:
                                resp = client.generate(request=request)
                            except Exception:
                                resp = None
                    # If we got a response, try to extract a function call in multiple ways
                    if resp is not None:
                        parsed = self._parse_function_call_from_payload(resp)
                        # also try parsing if resp is dict-like
                        if parsed is None:
                            try:
                                # convert to dict if possible
                                resp_dict = resp if isinstance(resp, dict) else None
                                # Some client objects expose a 'to_dict' or similar
                                if hasattr(resp, "to_dict"):
                                    try:
                                        resp_dict = resp.to_dict()
                                    except Exception:
                                        resp_dict = None
                                if resp_dict:
                                    parsed = self._parse_function_call_from_payload(resp_dict)
                            except Exception:
                                parsed = None
                        # If parsed, return consistent structure. Also include text if available.
                        raw_text = ""
                        try:
                            # attempt to extract a text candidate
                            # many Response objects provide an 'output' or 'candidates' text
                            if hasattr(resp, "output"):
                                outs = getattr(resp, "output")
                                if outs:
                                    first = outs[0]
                                    # first may contain content list with text items
                                    content = getattr(first, "content", None) or (first.get("content") if isinstance(first, dict) else None)
                                    if content:
                                        for c in content:
                                            if isinstance(c, dict) and c.get("type") == "output_text":
                                                raw_text = c.get("text") or raw_text
                                            elif isinstance(c, dict) and c.get("type") == "message":
                                                raw_text = raw_text or c.get("text")
                                            else:
                                                # try object
                                                raw_text = raw_text or getattr(c, "text", None) or raw_text
                            if not raw_text and hasattr(resp, "candidates"):
                                cands = getattr(resp, "candidates")
                                if cands:
                                    cand = cands[0]
                                    raw_text = getattr(cand, "content", None) or getattr(cand, "text", None) or (cand.get("text") if isinstance(cand, dict) else "")
                        except Exception:
                            raw_text = ""

                        out = {"raw_text": raw_text}
                        if parsed:
                            out["function_call"] = parsed
                        return out

                # Try other google-genai entrypoints defensively (module-level generate)
                if hasattr(gg, "generate"):
                    try:
                        resp = gg.generate(model=self.model, input=prompt)
                        parsed = self._parse_function_call_from_payload(resp)
                        if parsed:
                            return {"raw_text": "", "function_call": parsed}
                        return {"raw_text": str(resp)}
                    except Exception:
                        pass
            except Exception as exc:
                logger.exception("Error calling google-genai function call API: %s", exc)

        # Mocked function-call behavior when real client isn't available or didn't return a function call.
        lower = prompt.lower()
        if "depth chart" in lower or "depthchart" in lower:
            # crude extraction: try to find a team name and optional year
            import re

            team_match = re.search(r"(?:for|of|get\s)?\s*([A-Za-z ]+?)\s+(?:depth chart|depthchart)", prompt, re.IGNORECASE)
            if not team_match:
                # try to capture leading team name e.g. 'get Cardinals depth chart'
                team_match = re.search(r"get\s+([A-Za-z ]+?)\s+depth", prompt, re.IGNORECASE)

            team_name = team_match.group(1).strip() if team_match else ""

            year_match = re.search(r"(20\d{2}|\d{4})", prompt)
            year = int(year_match.group(1)) if year_match else None

            func_call = {
                "name": "get_depth_chart",
                "arguments": {"team_name": team_name, "year": year}
            }
            return {"raw_text": "", "function_call": func_call}

        # Default: return text only
        return {"raw_text": "I don't understand the request."}
