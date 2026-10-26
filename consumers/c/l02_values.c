/* Independent C11 oracle for the approved bounded-value recipe.
 * No producer implementation or generated rule is used as an oracle.
 * MADB_LAB_STUB proves only the public inline helper's protocol behavior. */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE 1
#endif
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>
#include <unistd.h>
#ifndef MADB_LAB_STUB
#include <dlfcn.h>
#endif
#include "reading_demo.h"
#include "reading_demo_native.h"
#include "madb_value_abi_v1.h"
#ifndef MADB_LAB_AUTHOR
#error MADB_LAB_AUTHOR must select the independently fixed author revision
#endif
#if MADB_LAB_AUTHOR < 0 || MADB_LAB_AUTHOR > 4
#error unsupported independent author revision
#endif
#if defined(MADB_LAB_MISMATCH_ONLY) && (defined(MADB_LAB_STUB) || (MADB_LAB_AUTHOR != 0 && MADB_LAB_AUTHOR != 2))
#error mixed consumer requires only the shared author-0 or author-2 ordinary entry
#endif
#if MADB_LAB_AUTHOR < 3
#define TRIM reading_demo_normalize
#define RAW_TRIM reading_demo_raw_normalize
#else
#define TRIM reading_demo_canonicalize
#define RAW_TRIM reading_demo_raw_canonicalize
#endif
static unsigned checks;
#define CHECK(e) do { ++checks; if (!(e)) { fprintf(stderr,"L02 values assertion:%d:%s\n",__LINE__,#e); exit(2); } } while (0)
_Static_assert(sizeof(MadbValueUtf8_64) == 68, "inline UTF-8 extent");
_Static_assert(_Alignof(MadbValueUtf8_64) == 4, "inline UTF-8 alignment");
_Static_assert(sizeof(MadbValueError) == 8, "error extent");
_Static_assert(_Alignof(MadbValueError) == 4, "error alignment");
#if MADB_LAB_AUTHOR < 2
_Static_assert(sizeof(reading_demo_Reading) == 72, "two-field record layout");
#else
_Static_assert(sizeof(reading_demo_Reading) == 76, "three-field record layout");
#endif
_Static_assert(_Alignof(reading_demo_Reading) == 4, "record alignment");
static int zero_value(const reading_demo_Reading *v) {
    if (v->value || v->label.byte_count) return 0;
#if MADB_LAB_AUTHOR >= 2
    if (v->quality) return 0;
#endif
    for (unsigned i=0; i<64; ++i) if (v->label.bytes[i]) return 0;
    return 1;
}
static reading_demo_Reading input_value(const uint8_t *p, uint32_t n) {
    reading_demo_Reading v = {0}; v.value=7; v.label.byte_count=n;
    if (n <= 64) memcpy(v.label.bytes,p,n);
#if MADB_LAB_AUTHOR >= 2
    v.quality=42;
#endif
    return v;
}
#ifndef MADB_LAB_MISMATCH_ONLY
static void tail_zero(const reading_demo_Reading *v) {
    CHECK(v->label.byte_count <= 64);
    for (uint32_t i=v->label.byte_count; i<64; ++i) CHECK(v->label.bytes[i] == 0);
}
static void success(reading_demo_ReadingResult r, int32_t value, const uint8_t *text, uint32_t n) {
    CHECK(r.kind == 0 && r.status == 0 && r.error.domain == 0 && r.error.code == 0);
    CHECK(r.value.value == value && r.value.label.byte_count == n);
    CHECK(memcmp(r.value.label.bytes,text,n) == 0); tail_zero(&r.value);
#if MADB_LAB_AUTHOR >= 2
    CHECK(r.value.quality == 42);
#endif
}
#endif
static void failure(reading_demo_ReadingResult r, uint32_t kind, int32_t status, uint32_t domain, int32_t code) {
    CHECK(r.kind==kind && r.status==status && r.error.domain==domain && r.error.code==code);
    CHECK(zero_value(&r.value));
}
static void parse_identity(const char *hex, uint8_t value[64]) {
    CHECK(strlen(hex)==128);
    for (unsigned i=0; i<64; ++i) { unsigned n=0; char pair[3]={hex[2*i],hex[2*i+1],0};
        CHECK(sscanf(pair,"%2x",&n)==1); value[i]=(uint8_t)n; }
}
#ifndef MADB_LAB_STUB
static void json_string(const char *value) {
    putchar('"');
    for (const unsigned char *p=(const unsigned char *)value; *p; ++p) {
        if (*p=='"' || *p=='\\') { putchar('\\'); putchar(*p); }
        else if (*p < 32) printf("\\u%04x",*p); else putchar(*p);
    }
    putchar('"');
}
static void binding(const char *expected) {
    uint8_t identity[64], want[64]; parse_identity(expected,want);
    CHECK(reading_demo_bootstrap_v1(1,identity,64)==0);
    CHECK(memcmp(identity,want,64)==0);
    Dl_info image; CHECK(dladdr((void *)(uintptr_t)reading_demo_bootstrap_v1,&image)!=0);
    CHECK(image.dli_fname != NULL);
    printf("{\"event\":\"binding\",\"image\":"); json_string(image.dli_fname);
    printf(",\"identity\":\""); for (unsigned i=0;i<64;++i) printf("%02x",identity[i]);
    printf("\",\"pid\":%ld}\n",(long)getpid());
}
#ifndef MADB_LAB_MISMATCH_ONLY
static void values(void) {
    const uint8_t padded[]={32,32,0xe6,0xb8,0xa9,0xe5,0xba,0xa6,32,32};
    const uint8_t trimmed[]={0xe6,0xb8,0xa9,0xe5,0xba,0xa6};
    reading_demo_Reading v=input_value(padded,sizeof padded), original=v;
    success(TRIM(v),7,trimmed,sizeof trimmed); CHECK(memcmp(&v,&original,sizeof v)==0);
    const uint8_t nul[]={97,0,98}, supplementary[]={0xf0,0x9f,0x8c,0xa1};
    success(TRIM(input_value(nul,0)),7,nul,0);
    success(TRIM(input_value(nul,sizeof nul)),7,nul,sizeof nul);
    success(TRIM(input_value(supplementary,sizeof supplementary)),7,supplementary,sizeof supplementary);
    uint8_t full[64]; memset(full,'x',sizeof full);
    success(TRIM(input_value(full,64)),7,full,64);
    for(unsigned i=0;i<64;i+=4) memcpy(full+i,supplementary,4);
    success(TRIM(input_value(full,64)),7,full,64);
    v=input_value(nul,sizeof nul); memset(v.label.bytes+sizeof nul,0xa5,64-sizeof nul); original=v;
    success(TRIM(v),7,nul,sizeof nul); CHECK(memcmp(&v,&original,sizeof v)==0);
    v=input_value(nul,sizeof nul); v.value=INT32_MIN; success(TRIM(v),INT32_MIN,nul,sizeof nul);
    v.value=INT32_MAX; success(TRIM(v),INT32_MAX,nul,sizeof nul);
#if MADB_LAB_AUTHOR >= 2
    v.quality=UINT32_MAX; reading_demo_ReadingResult high=TRIM(v);
    CHECK(high.kind==0 && high.status==0 && high.value.quality==UINT32_MAX); tail_zero(&high.value);
#endif
#if MADB_LAB_AUTHOR >= 1 && MADB_LAB_AUTHOR <= 3
    v=input_value(padded,sizeof padded); original=v;
    success(reading_demo_offset(v,5),12,padded,sizeof padded); CHECK(memcmp(&v,&original,sizeof v)==0);
    v.value=INT32_MAX; failure(reading_demo_offset(v,1),4,10,1,1);
    v.value=INT32_MIN; failure(reading_demo_offset(v,-1),4,10,1,1);
    v.value=0; success(reading_demo_offset(v,INT32_MAX),INT32_MAX,padded,sizeof padded);
    CHECK(reading_demo_ReadingError_Overflow==1);
#endif
}
static void raw_rejections(void) {
    const uint8_t empty[]={0}; reading_demo_Reading v=input_value(empty,0), out;
    MadbValueError error;
    const uint8_t bad[][5]={{0x80},{0xc0,0xaf},{0xe2,0x82},{0xed,0xa0,0x80},{0xf4,0x90,0x80,0x80},{0xf0,0x9f,0x8c,0xa1,0x80}};
    const uint32_t lengths[]={1,2,2,3,4,5};
    for (unsigned i=0;i<sizeof lengths/sizeof lengths[0];++i) {
        v=input_value(bad[i],lengths[i]); reading_demo_Reading original=v;
        failure(TRIM(v),4,1,0,0); CHECK(memcmp(&v,&original,sizeof v)==0);
    }
    v=input_value(empty,65); failure(TRIM(v),4,1,0,0);
    memset(&out,0xa5,sizeof out); error=(MadbValueError){7,9};
    CHECK(RAW_TRIM(NULL,&out,&error)==1 && zero_value(&out) && error.domain==0 && error.code==0);
    v=input_value(empty,0); error=(MadbValueError){7,9}; CHECK(RAW_TRIM(&v,NULL,&error)==1 && error.domain==0 && error.code==0);
    memset(&out,0xa5,sizeof out); CHECK(RAW_TRIM(&v,&out,NULL)==1 && zero_value(&out));
    CHECK(RAW_TRIM(&v,NULL,NULL)==1);
    _Alignas(reading_demo_Reading) unsigned char input_storage[sizeof v+8]; memset(input_storage,0,sizeof input_storage);
    memset(&out,0xa5,sizeof out); error=(MadbValueError){7,9};
    CHECK(RAW_TRIM((const reading_demo_Reading *)(const void *)(input_storage+1),&out,&error)==1);
    CHECK(zero_value(&out) && error.domain==0 && error.code==0);
    _Alignas(reading_demo_Reading) unsigned char output_storage[sizeof out+8]; memset(output_storage,0xa5,sizeof output_storage);
    error=(MadbValueError){7,9}; CHECK(RAW_TRIM(&v,(reading_demo_Reading *)(void *)(output_storage+1),&error)==1);
    CHECK(error.domain==0 && error.code==0); for(unsigned i=0;i<sizeof output_storage;++i) CHECK(output_storage[i]==0xa5);
    _Alignas(MadbValueError) unsigned char error_storage[sizeof error+8]; memset(error_storage,0xa5,sizeof error_storage);
    memset(&out,0xa5,sizeof out); CHECK(RAW_TRIM(&v,&out,(MadbValueError *)(void *)(error_storage+1))==1);
    CHECK(zero_value(&out)); for(unsigned i=0;i<sizeof error_storage;++i) CHECK(error_storage[i]==0xa5);
}
static void bootstrap(void) {
    uint8_t bytes[65]; memset(bytes,0xa5,sizeof bytes);
    CHECK(reading_demo_bootstrap_v1(1,bytes,63)==1); for(unsigned i=0;i<65;++i) CHECK(bytes[i]==0xa5);
    CHECK(reading_demo_bootstrap_v1(1,bytes,65)==1); for(unsigned i=0;i<65;++i) CHECK(bytes[i]==0xa5);
    CHECK(reading_demo_bootstrap_v1(1,NULL,64)==1);
    CHECK(reading_demo_bootstrap_v1(2,bytes,64)==11); for(unsigned i=0;i<64;++i) CHECK(bytes[i]==0);
    CHECK(bytes[64]==0xa5);
}
#endif
#else
static uint8_t expected_identity[64];
static unsigned boot_calls, raw_calls, mode;
MadbValueStatus reading_demo_bootstrap_v1(uint32_t version,uint8_t *out,uint64_t capacity) {
    ++boot_calls; CHECK(version==1 && capacity==64 && out!=NULL);
    memcpy(out,expected_identity,64);
    if (mode==1) return 11;
    if (mode==5) return 5;
    if (mode==20) return 1;
    if (mode==21) return 8;
    if (mode==22) return 9;
    if (mode==2 || mode==4) out[0]^=1;
    if (mode==3 || mode==4) out[32]^=1;
    return 0;
}
static MadbValueStatus provider(const reading_demo_Reading *input,reading_demo_Reading *out,MadbValueError *error,int fallible) {
    ++raw_calls; CHECK(input && out && error); CHECK(zero_value(out)); CHECK(error->domain==0 && error->code==0);
    memset(out,0,sizeof *out); *error=(MadbValueError){0,0};
    if (mode==6) return 5;
    if (mode==11) {out->value=1; return 1;}
    if (mode==12 || mode==13 || mode==18) {error->domain=1;error->code=mode==13 ? 99 : 1; CHECK(fallible || mode!=18);return 10;}
    if (mode==14) {error->domain=1;error->code=1;return 8;}
    if (mode==15) return 1;
    if (mode==16) return 9;
    if (mode==17) return 8;
    if (mode==23) return 11;
    *out=*input; memset(out->label.bytes+out->label.byte_count,0,64-out->label.byte_count);
    if (mode==7) error->code=1;
    if (mode==8) out->label.byte_count=65;
    if (mode==9) {out->label.byte_count=1;out->label.bytes[0]=0x80;}
    if (mode==10) out->label.bytes[63]=1;
    return 0;
}
MadbValueStatus RAW_TRIM(const reading_demo_Reading *input,reading_demo_Reading *out,MadbValueError *error) {return provider(input,out,error,0);}
#if MADB_LAB_AUTHOR >= 1 && MADB_LAB_AUTHOR <= 3
MadbValueStatus reading_demo_raw_offset(const reading_demo_Reading *input,int32_t delta,reading_demo_Reading *out,MadbValueError *error) {
    CHECK(delta==5);return provider(input,out,error,1);
}
#endif
static unsigned helper_protocol(const char *hex) {
    parse_identity(hex,expected_identity); const uint8_t text[]={'a'}; unsigned vectors=0;
    for(mode=0;mode<=23;++mode) {
        if(mode==18 || mode==19) continue;
        boot_calls=raw_calls=0; reading_demo_Reading v=input_value(text,1);
        if(mode==1 || mode==2 || mode==3 || mode==4 || mode==5 || mode>=20) v.label.byte_count=65;
        reading_demo_ReadingResult result=TRIM(v); ++vectors;
        CHECK(boot_calls==1);
        if(mode==0) {success(result,7,text,1);CHECK(raw_calls==1);}
        else if(mode==1 || mode==5 || mode==20 || mode==21 || mode==22) {
            failure(result,1,mode==1 ? 11 : mode==20 ? 1 : mode==22 ? 9 : 8,0,0); CHECK(raw_calls==0);
        } else if(mode==2 || mode==4) {failure(result,2,11,0,0);CHECK(raw_calls==0);}
        else if(mode==3) {failure(result,3,11,0,0);CHECK(raw_calls==0);}
        else {failure(result,4,mode==15 ? 1 : mode==16 ? 9 : 8,0,0);CHECK(raw_calls==1);}
    }
#if MADB_LAB_AUTHOR >= 1 && MADB_LAB_AUTHOR <= 3
    for(mode=13;mode<=18;mode+=5) {
        boot_calls=raw_calls=0;reading_demo_ReadingResult r=reading_demo_offset(input_value(text,1),5);++vectors;
        CHECK(boot_calls==1 && raw_calls==1);
        if(mode==18) failure(r,4,10,1,1);else failure(r,4,8,0,0);
    }
#endif
    return vectors;
}
#endif
int main(int argc,char **argv) {
    CHECK(argc>=2); const char *selected=argv[1]; unsigned vectors=0;
#ifdef MADB_LAB_STUB
    CHECK(argc==3 && strcmp(selected,"helper-protocol")==0); vectors=helper_protocol(argv[2]);
#else
    CHECK(argc==4); binding(argv[3]);
#ifdef MADB_LAB_MISMATCH_ONLY
    CHECK(strcmp(selected,"mismatch")==0);
    const uint8_t empty[]={0};reading_demo_Reading value=input_value(empty,65);
    failure(TRIM(value),2,11,0,0);
#else
    if(strcmp(selected,"values")==0) values();
    else if(strcmp(selected,"raw-rejections")==0) raw_rejections();
    else if(strcmp(selected,"bootstrap")==0) bootstrap();
    else if(strcmp(selected,"mismatch")==0) {
        const uint8_t empty[]={0};reading_demo_Reading value=input_value(empty,65);
        failure(TRIM(value),2,11,0,0);
    } else CHECK(0);
#endif
#endif
    printf("{\"result\":\"passed\",\"mode\":\"%s\",\"author\":%d,\"checks\":%u,\"helper_vectors\":%u,\"scope\":\"%s\"}\n",selected,MADB_LAB_AUTHOR,checks,vectors,
#ifdef MADB_LAB_STUB
           "helper-only"
#else
           "native-sdk"
#endif
    );
    return 0;
}
