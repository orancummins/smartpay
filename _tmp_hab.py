from app import config, analytics
from app.dashboard_server import provider

profile = provider.get_profile(config.DEMO_CUSTOMER_ID)
non_mc = {i.display_name for i in profile.instruments if i.is_card and not i.is_mastercard}
print("Non-Mastercards:", non_mc)

for name, hist in (("retro", analytics.retrospective_history(profile)),):
    offenders = [c["label"] for c in hist["habit_changes"]
                 if c["label"].startswith("Use ")
                 and c["label"].split(" instead of")[0].replace("Use ", "") in non_mc]
    print(name, "habit_changes:", len(hist["habit_changes"]),
          "| non-MC swap targets:", offenders)
    for c in hist["habit_changes"]:
        print("   ", c["label"])
