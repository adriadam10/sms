#include <MoveBG/MapObjBall.hpp>
#include <MoveBG/MapObjGeneral.hpp>
#include <System/FlagManager.hpp>
#include <System/MarDirector.hpp>

// Native port of TResetFruit::perform (@0x801e21d0, someone/main@87df2a96).
// TResetFruit is the "無限フルーツ" (infinite fruit) -- the respawnable
// coconut/fruit found on beaches, including the file-select stage's beach.
// Its perform() is a thin dispatch: handle a Pinna Park (stage 7) Yoshi-touch
// special case, else fall through to the parent's perform. File-select is
// stage 15, so the Pinna Park branch is never entered there; adding this
// vtable slot makes the coconut model's calc/entry/draw actually run instead
// of no-op'ing, via the parent delegation.
//
// DOCUMENTED GAP (kept honest, not adapted here): the stage-7 branch BODY
// (Yoshi-touch state machine + several unresolved vtable calls) is not
// reproduced -- upstream's own commit message flags this as incomplete, and
// the "at-rest" velocity threshold there is a placeholder (not the real SDA2
// constant). Never fires outside Pinna Park (stage 7), so untestable against
// our file-select-reachable target; not cherry-picked, this file only has
// the parent-delegation shell.
void TResetFruit::perform(u32 param_1, JDrama::TGraphics* param_2)
{
	TMapObjGeneral::perform(param_1, param_2);
}

// Native port of TCoverFruit::loadAfter (@0x801e1748, someone/main@3bb0d1a6).
// フタのフルーツ ("lid fruit"): after the base loadAfter, check the "was this
// fruit already collected in this save" boolean; if set, kill the object at
// load time via makeObjDead() so it never appears. TCoverFruit does not
// override makeObjDead, so this dispatches TMapObjBase::makeObjDead (zeros
// velocity, sets mLiveFlag bit 0x10).
void TCoverFruit::loadAfter()
{
	TMapObjBase::loadAfter();
	if (TFlagManager::getInstance()->getBool(0x1038B)) {
		makeObjDead();
	}
}
