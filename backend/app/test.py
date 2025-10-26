from ai_speaker import think_ai_utterance, plan_and_speak

demo_history = """\
[Day 1]  
Player 1 (confident): “We need to speak up early. Silence only helps wolves. I suggest everyone share first impressions.”  
Player 2 (calm): “Everyone seems nervous… especially Player 5 glancing around.”  
Player 3 (anxious): “I’m just trying to understand. Please don’t target newbies right away.”  
Player 4 (aggressive): “Don’t deflect to me! That’s a bad wolf tactic!”  
Player 5 (me)(obervant): “Player 3’s stutter feels like a cover. Also Player 8 hasn’t talked yet.”  
Player 6 (neutral): “Let’s not rush. Someone give us real info.”  
Player 7 (joking): “Well I’m a villager. 100% guaranteed by the universe.”  
Player 8 (reserved): “Sorry, just listening. Not much to say yet.”  

> Players 3 and 5 both got 4 votes.

Player 5 defended strongly after a weak accusation. (frustrated)

Result: No execution (votes scattered)

----------------------------------------------------

[Night 1]  
Wolves whisper and hesitate. (confused)  
No kill. Wolves are confused.

----------------------------------------------------

[Day 2]  
Player 1 (alert): “No kill at night? Wolves blundered. Player 5’s defense still feels exaggerated.”  
Player 2 (suspicious): “Could be 3 pretending to be nervous. I want answers.”  
Player 3 (cornered): “Why me again? If I were wolf I’d push someone harder.”  
Player 4 (tense): “Player 8 still low participation = suspicious.”  
Player 5 (angry): “Stop making me the easy target! Look at Player 2’s quiet manipulation.”  
Player 6 (me)(surprised): 
"""

print("=== TEST: Thinking only ===")
# plan = think_ai_utterance(demo_history)
# print(plan)

# 如果你环境已配置好 TTS 数据集依赖，就打开下面这一行：
print("\n=== TEST: Plan → Speak (audio) ===")
# 生成情绪语音（自动根据 plan 的 emotion/actor/intensity）
out_path = "test_plan_and_speak.wav"
final_plan = plan_and_speak(demo_history, out_name=out_path)
print("Saved:", out_path)
print("Final plan:", final_plan)
