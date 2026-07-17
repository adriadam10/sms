#include <MoveBG/MapObjBall.hpp>
#include <System/FlagManager.hpp>

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
