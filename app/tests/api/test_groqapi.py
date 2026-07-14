from app.llm import get_llm

llm = get_llm()

response = llm.invoke("Say hello in one sentence.")

print(response.content)