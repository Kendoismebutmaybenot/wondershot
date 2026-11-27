#include "../../host/wonder_online/online_ui.h"
#include <cassert>
#include <cstring>
#include <cstdio>
int main(int argc,char **argv) {
    assert(argc==2);
    auto uid=wonder_profile_uid(); auto save=wonder_profile_save_uid();
    assert((uid[0] || uid[1]) && save[0]==1 && save[1]==0x5a3c9e1f0b7d2468ULL);
    if (!std::strcmp(argv[1],"broken")) {
        assert(!wonder_profile_available() && !wonder_profile_enabled());
        assert(uid[0]==save[0] && uid[1]==save[1]);
    } else {
        assert(wonder_profile_available());
        auto low=uid[0], high=uid[1];
        if (!std::strcmp(argv[1],"create")) {
            assert(wonder_profile_set_name("Test player"));
            assert(!wonder_profile_set_name("   "));
            assert(wonder_profile_set_privacy(0) && !wonder_profile_privacy());
            assert(wonder_profile_set_privacy(1) && wonder_profile_privacy());
        }
        char name[33];wonder_profile_name(name,sizeof name);assert(!std::strcmp(name,"Test player"));
        assert(uid[0]==low && uid[1]==high);
    }
    puts("PASS profile identity and save mapping checks");
}
