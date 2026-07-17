#include <MoveBG/MapObjPinna.hpp>

// Native port of THorizontalViking::reset (@0x801d6664, 52 bytes,
// someone/main@2e74ee57). バイキング船 ("Viking ship") -- the Pinna Park
// pirate-swing ride. Copies the target swing angle (unk140) into the
// current-angle slot (unk144), zeros the angular velocity (unk148), and
// latches the starting direction into mState: 1 if the target is > 0, else 2.
void THorizontalViking::reset()
{
	unk144 = unk140;
	unk148 = 0.0f;
	mState = (unk140 > 0.0f) ? 1 : 2;
}

// Native port of TViking::loadAfter (@0x801d6090, 64 bytes,
// someone/main@2e74ee57). バイキング -- TViking IS a THorizontalViking (per
// header). loadAfter forwards to the base TMapObjBase::loadAfter, then
// virtually invokes THorizontalViking::reset via vtable slot 0x164 (the first
// slot beyond TMapObjBase's own vtable). TViking has its own reset() which is
// a DIFFERENT, non-virtual, longer function -- NOT an override of this slot.
void TViking::loadAfter()
{
	TMapObjBase::loadAfter();
	THorizontalViking::reset();
}
