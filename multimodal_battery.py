"""Multimodal test battery — settles what actually works in the installed stack.

T1  ollama + ImageFile via Crew.kickoff()            (project's native path)
T2  ollama + ImageFile via agent.kickoff()           (docs 'standalone agent' path)
T3  gemini + ImageFile via Flow.kickoff -> crew      (docs 'with flows' path)
T4  gemini + ImageFile via agent.kickoff()           (docs 'standalone agent' path)
T5  gemini + ImageFile via task.execute_sync()       (APOEMA Flow's actual pattern)
T6  ollama + ImageFile via Crew.kickoff() with shim  (supports_multimodal + provider override)
T7  raw Ollama /v1 chat with base64 image            (baseline: Ollama API itself)

Each test reports PASS (image reached the model) / DROP (no image) / ERROR.
"""
import base64
import json
import os
import sys
import urllib.request

from dotenv import load_dotenv

load_dotenv()

IMG = "input/formacao-docentes.png"
PROMPT = (
    "You receive an attached image. If you can SEE it, answer exactly "
    "'IMAGE_OK <one word>'. Otherwise answer exactly 'NO_IMAGE'."
)
TIMEOUT = 300


def make_llm(kind: str):
    from crewai import LLM

    if kind == "gemini":
        return LLM(model="gemini/gemini-3-flash-preview", api_key=os.getenv("GEMINI_API_KEY"))
    if kind == "ollama":
        return LLM(model="ollama/qwen2.5vl:3b", base_url="http://localhost:11434")
    raise ValueError(kind)


def verdict(text: str) -> bool:
    return "IMAGE_OK" in text.upper() and "NO_IMAGE" not in text.upper()


def run(label: str, fn):
    try:
        out = fn()
        ok = verdict(str(out))
        print(f"[{'PASS' if ok else 'DROP'}] {label}: {str(out)[:120]}")
    except Exception as e:
        print(f"[ERROR] {label}: {type(e).__name__}: {str(e)[:180]}")


def t1():
    from crewai import Agent, Crew, Task
    from crewai_files import ImageFile

    llm = make_llm("ollama")
    agent = Agent(role="tester", goal="answer", backstory="tester", llm=llm)
    task = Task(description=PROMPT, expected_output="one line", agent=agent,
                input_files={"img": ImageFile(source=IMG)})
    return Crew(agents=[agent], tasks=[task]).kickoff()


def t2():
    from crewai import Agent
    from crewai_files import ImageFile

    llm = make_llm("ollama")
    agent = Agent(role="tester", goal="answer", backstory="tester", llm=llm)
    return agent.kickoff(messages=PROMPT, input_files={"img": ImageFile(source=IMG)})


def t3():
    from crewai import Agent, Crew, Task
    from crewai.flow.flow import Flow, start
    from crewai_files import ImageFile

    llm = make_llm("gemini")
    agent = Agent(role="tester", goal="answer", backstory="tester", llm=llm)
    task = Task(description=PROMPT, expected_output="one line", agent=agent,
                input_files={"img": ImageFile(source=IMG)})
    inner = Crew(agents=[agent], tasks=[task])

    class F(Flow):
        @start()
        def run(self):
            return inner.kickoff()

    return F().kickoff(input_files={"img": ImageFile(source=IMG)})


def t4():
    from crewai import Agent
    from crewai_files import ImageFile

    llm = make_llm("gemini")
    agent = Agent(role="tester", goal="answer", backstory="tester", llm=llm)
    return agent.kickoff(messages=PROMPT, input_files={"img": ImageFile(source=IMG)})


def t5():
    from crewai import Agent, Task
    from crewai_files import ImageFile

    llm = make_llm("gemini")
    agent = Agent(role="tester", goal="answer", backstory="tester", llm=llm)
    task = Task(description=PROMPT, expected_output="one line", agent=agent,
                input_files={"img": ImageFile(source=IMG)})
    return task.execute_sync()


def t6():
    from crewai import Agent, Crew, Task
    from crewai_files import ImageFile

    llm = make_llm("ollama")
    # Shim: tell CrewAI this model speaks vision, and route file formatting
    # through the OpenAI formatter (same image_url data-URI payload Ollama accepts).
    llm.supports_multimodal = lambda: True
    llm.provider = "openai"
    agent = Agent(role="tester", goal="answer", backstory="tester", llm=llm)
    task = Task(description=PROMPT, expected_output="one line", agent=agent,
                input_files={"img": ImageFile(source=IMG)})
    return Crew(agents=[agent], tasks=[task]).kickoff()


def t7():
    b64 = base64.b64encode(open(IMG, "rb").read()).decode()
    payload = json.dumps({
        "model": "qwen2.5vl:3b",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]}],
        "stream": False,
    }).encode()
    req = urllib.request.Request("http://localhost:11434/v1/chat/completions",
                                 data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read())["choices"][0]["message"]["content"]


if __name__ == "__main__":
    tests = {"t1": t1, "t2": t2, "t3": t3, "t4": t4, "t5": t5, "t6": t6, "t7": t7}
    only = sys.argv[1] if len(sys.argv) > 1 else None
    for name, fn in tests.items():
        if only and name != only:
            continue
        run(name, fn)
